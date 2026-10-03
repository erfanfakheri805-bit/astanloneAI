"""
Agent - Agent Loop
=====================
`AgentLoop` is a small, deterministic coordinator sitting directly on
top of the Planning/Execution stack that already exists in this
project:

    GOAL (planning/goal.py) + PLAN (planning/plan.py)
        -> GoalCompletionEvaluator.evaluate  (planning/goal_completion.py:
           read-only "has this Plan already satisfied this Goal?")
        -> [only if not already satisfied]
           PlanExecutionController.execute_plan  (execution/
           plan_execution_controller.py: run as many of the Plan's
           already-eligible steps as can safely run right now -
           unchanged)
        -> GoalCompletionEvaluator.evaluate again (re-check what the
           execution actually accomplished)
        -> a single, structured AgentLoop.run() result dict

This module answers exactly one question - "given this already-
existing Goal and this already-existing Plan, should anything run
right now, and if so, run the existing Plan through the existing
execution stack (never a second copy of it) and report exactly what
happened" - and nothing broader than that. It does not create a Goal,
does not create a Plan, does not generate a step, does not invent a
capability, and does not decide *how* a single step runs (that
remains `StepExecutionController`/`ExecutionEngine`'s job, reused
unchanged via `PlanExecutionController`).

Every rule this module applies already exists somewhere else in this
project; `AgentLoop` never re-derives any of them, it only calls into
them, in order, and reads their already-structured results:

  - "does this Goal exist" / "does this Plan exist" / "does this Plan
    actually belong to this Goal" reuses `GoalManager.get_goal`,
    `PlanManager.get_plan`, and `Plan.goal_id` - the exact same checks
    `GoalCompletionEvaluator.evaluate` itself already performs, in the
    same order;
  - "has this Plan already satisfied this Goal" reuses
    `GoalCompletionEvaluator.evaluate` (planning/goal_completion.py)
    unchanged, both before and after execution;
  - "run as much of this Plan as can safely run right now" reuses
    `PlanExecutionController.execute_plan`
    (execution/plan_execution_controller.py) unchanged - cycle
    detection, the per-step READY/executable check, preparation,
    capability execution, `ExecutionResult`/`ExecutionHistory`/
    `ExecutionEventLog` recording, and the step's own COMPLETED/FAILED
    status transition all continue to happen exactly where they
    already did;
  - "which step, if any, would run next" (reported, never executed,
    whenever the Goal is not satisfied) reuses `PlanExecutionCoordinator.
    get_next_ready_step` (execution/plan_execution_coordinator.py)
    unchanged, via `self._controller.coordinator` - the exact same
    coordinator instance/registries `PlanExecutionController.
    execute_plan` itself already calls into, never a second,
    disagreeing coordinator;
  - every AgentLoop-level event is recorded through the exact same
    `ExecutionEventLog` (execution/execution_event_log.py) and
    `ExecutionEvent` (execution/execution_event.py) records the rest
    of the execution stack already uses - never a second, parallel
    event system.

Nothing in this module:
  - creates a new `Goal` or a new `Plan` - it only ever operates on a
    `goal_id`/`plan_id` a caller already created via
    `GoalManager.create_goal`/`PlanManager.create_plan`;
  - creates, installs, enables, or discovers a capability;
  - rewrites, generates, or evaluates any code - no dynamic code
    evaluation, no dynamic code compilation, no child-process
    spawning, no shell command, no dynamic import, and no filesystem
    access of its own;
  - opens a network connection, or calls an external AI API;
  - implements automatic retry - a FAILED plan/step is left exactly
    as `PlanExecutionController` already left it; `AgentLoop.run`
    itself is never called recursively, and a single `run()` call
    never re-attempts a step or a plan that has already failed;
  - allows unbounded execution - `max_iterations` is always a
    required-finite, validated, positive integer (default `1`), and
    each iteration can perform at most one `PlanExecutionController.
    execute_plan` call, itself already internally bounded by that
    controller's own `max_steps_per_run` safety cap.

Deterministic (matches the "no fake intelligence" convention already
documented by reasoning/reasoning_result.py and
planning/goal_completion.py): every decision below is made only from
already-observed Goal/Plan/step state and the structured results
`GoalCompletionEvaluator`/`PlanExecutionController` already return -
never a guess, never randomized, and never based on anything outside
this project's own recorded state.
"""

from planning.goal_manager import GoalManager
from planning.plan_manager import PlanManager
from planning.goal_completion import (
    GoalCompletionEvaluator,
    STATE_SATISFIED,
    STATE_BLOCKED,
    STATE_FAILED,
    STATE_UNKNOWN,
)

from execution.plan_execution_controller import (
    PlanExecutionController,
    PLAN_RUN_BLOCKED,
    PLAN_RUN_WAITING,
)
from execution.execution_event import (
    ExecutionEvent,
    SEVERITY_INFO,
    SEVERITY_ERROR,
    EVENT_AGENT_LOOP_STARTED,
    EVENT_AGENT_ITERATION_STARTED,
    EVENT_AGENT_EVALUATION_COMPLETED,
    EVENT_AGENT_EXECUTION_COMPLETED,
    EVENT_AGENT_LOOP_COMPLETED,
    EVENT_AGENT_LOOP_STOPPED,
    EVENT_AGENT_LOOP_FAILED,
)
from execution.execution_event_log import ExecutionEventLog
from planning.adaptive_plan_analyzer import AdaptivePlanAnalyzer, ANALYSIS_COMPLETE, ANALYSIS_UNKNOWN
from planning.adaptive_plan_proposal import AdaptivePlanProposal
from planning.proposal_applier import ProposalApplier
from planning.proposal_history import ProposalHistory
from learning.learning_record_store import LearningRecordStore
from .test_result_evaluation import build_test_evaluation, build_correction_decision
from .code_change_evaluation import build_code_change_evaluation, build_code_change_correction_decision
from .generated_code_execution_evaluation import build_generated_code_execution_evaluation
from .code_error_analysis import build_code_error_analysis
from .code_correction_proposal import build_code_correction_proposal
from .code_correction_proposal_validation import build_code_correction_proposal_validation
from .code_correction_application import build_code_correction_application
from .code_change_self_upgrade_adapter import build_self_upgrade_input_from_code_correction
from .code_change_self_upgrade_validation import build_code_change_self_upgrade_readiness
from .code_change_self_upgrade_audit import CodeChangeAuditLog
from .code_change_version_snapshot import build_code_change_version_snapshot
from .code_change_rollback import build_code_change_rollback_decision
from .code_change_upgrade_result import build_code_change_upgrade_result
from .code_change_upgrade_state import (
    STATE_IDLE as UPGRADE_STATE_IDLE,
    STATE_IN_PROGRESS as UPGRADE_STATE_IN_PROGRESS,
    can_start_upgrade,
    next_upgrade_state_from_result,
)
from self_upgrade.version_system import VersionSystem
from self_upgrade.capability_evaluation import evaluate_capability_test_result as _evaluate_capability_test_result
from self_upgrade.capability_correction_analysis import build_capability_correction_analysis as _build_capability_correction_analysis
from self_upgrade.capability_correction_apply import apply_capability_correction as _apply_capability_correction
from self_upgrade.capability_correction_verification import verify_capability_correction as _verify_capability_correction
from self_upgrade.capability_approval_gate import evaluate_self_upgrade_approval_gate as _evaluate_self_upgrade_approval_gate
from self_upgrade.capability_registration_preparation import prepare_capability_registration as _prepare_capability_registration
from self_upgrade.capability_registration_plan import build_capability_registration_plan as _build_capability_registration_plan
from self_upgrade.capability_registration_approval import request_capability_registration_approval as _request_capability_registration_approval
from self_upgrade.capability_lifecycle import build_capability_lifecycle_state as _build_capability_lifecycle_state
from self_upgrade.capability_lifecycle_decision import build_capability_lifecycle_decision as _build_capability_lifecycle_decision
from .code_correction_retest import build_code_correction_retest
from .code_correction_learning import build_code_correction_learning_record
from .code_correction_pattern_retrieval import retrieve_successful_correction_patterns
from execution.python_test_runner_capability import CAPABILITY_NAME as _PYTHON_TEST_RUNNER_CAPABILITY_NAME
from planning.tool_step_dispatch import resolve_tool_step_dispatch
from .tool_step_intent import build_tool_step_intent
from .tool_step_runner import run_tool_step_intent

# Sentinel step_id used for AgentLoop-level events, which describe the
# loop's own decisions rather than any single PlanStep. Deliberately
# distinct from real step ids, which always look like
# "{plan_id}-step-{n}" (see planning/plan_manager.py's add_step) so an
# AgentLoop event can never be mistaken for a step-level one.
_AGENT_STEP_ID = "agent-loop"

# Fallback used only when a caller passes a plan_id that isn't even a
# usable string (e.g. an unknown/None plan_id) - ExecutionEvent itself
# always requires a non-empty string plan_id/step_id (see
# execution_event.py), so AgentLoop-level events still need something
# to record even while reporting that the plan_id was invalid.
_UNKNOWN_PLAN_ID_FOR_EVENTS = "agent-loop-unknown-plan"

# Small, fixed vocabulary for AgentLoop's own run-level outcome -
# distinct from (but derived from) GoalCompletionEvaluator's own
# STATE_* vocabulary, which is always reported separately as
# "goal_status" in the result dict. Same STATUS_*/ALL_* controlled-
# vocabulary convention already used throughout this project (see
# planning/goal.py, planning/plan.py, planning/goal_completion.py,
# execution/plan_execution_controller.py).
STATUS_SATISFIED = "satisfied"
STATUS_FAILED = "failed"
STATUS_BLOCKED = "blocked"
STATUS_NOT_SATISFIED = "not_satisfied"
STATUS_UNKNOWN = "unknown"
STATUS_MAX_ITERATIONS_REACHED = "max_iterations_reached"
STATUS_INVALID = "invalid"

ALL_AGENT_LOOP_STATUSES = (
    STATUS_SATISFIED, STATUS_FAILED, STATUS_BLOCKED, STATUS_NOT_SATISFIED,
    STATUS_UNKNOWN, STATUS_MAX_ITERATIONS_REACHED, STATUS_INVALID,
)

# Every status except FAILED/INVALID is reported with success=True -
# "not satisfied yet" or "blocked" or "ran out of budgeted iterations"
# are all honest, structured outcomes, not failures of the loop
# itself. Kept as a set (not an inline literal) so `_finish` never has
# to re-decide this per call.
_FAILURE_STATUSES = frozenset({STATUS_FAILED, STATUS_INVALID})


class AgentLoop:
    """Not thread-safe (matches the rest of this project - see
    PlanExecutionController/GoalCompletionEvaluator's own notes). Safe
    to use one instance per Core / per conversation session.

    Every collaborator this loop needs already exists elsewhere in
    this project. `goal_manager`, `plan_manager`, and
    `plan_execution_controller` are required - same "wired to the
    managers/controller it reads from" relationship every other
    execution-stack class already has.

    `goal_completion_evaluator`, if given, is used exactly as
    provided. When omitted, a new `GoalCompletionEvaluator` is built
    from `goal_manager`/`plan_manager` - never a second, disagreeing
    implementation of Goal-completion logic.

    `event_log`, if given, is used exactly as provided. When omitted,
    this loop reuses `plan_execution_controller.event_log` - the exact
    same `ExecutionEventLog` `PlanExecutionController`/
    `StepExecutionController`/`ExecutionEngine` already write to, so a
    caller inspecting one event log sees the whole picture (step-level
    events and AgentLoop-level events together, in one timeline).

    `analyzer` (added alongside planning/adaptive_plan_analyzer.py), if
    given, must be an `AdaptivePlanAnalyzer`. It is stored but never
    consulted from inside `run()` itself - `run()`'s own decision logic
    (requirements unchanged, backward compatible) never depends on it.
    It exists purely so a caller can invoke `request_analysis` (below)
    after `run()` reports the Goal is not yet satisfied, without having
    to construct/wire a separate `AdaptivePlanAnalyzer` by hand.

    `proposal_generator` (added alongside planning/adaptive_plan_proposal.py),
    if given, must be an `AdaptivePlanProposal`. Same story as
    `analyzer`: stored but never consulted from inside `run()`, and
    exists purely so a caller can invoke `request_proposal` (below)
    without wiring a separate `AdaptivePlanProposal` by hand. `run()`
    never applies a proposal automatically - `request_proposal` itself
    only ever returns the read-only proposal, never any way to act on it.

    `learning_record_store` (added alongside
    learning/learning_record_store.py / learning/execution_learning.py),
    if given, must be a `LearningRecordStore` - the exact same store a
    caller (e.g. `Core.execute_first_step`) may already be adding
    `ExecutionLearning`-built records into. Unlike `analyzer`/
    `proposal_generator`, this one *is* read from inside `run()` -
    see `run()`'s own docstring for exactly when and how - but only
    ever read: `run()` never adds, removes, or modifies a record in
    it, never builds a new `LearningRecord`, and never changes what it
    executes based on what it reads back (requirement: "do not
    automatically modify the plan based on learning yet"). Omitting
    it (the default, `None`) is always safe - `run()` simply reports
    no relevant learning records, exactly as if the store existed but
    happened to be empty (requirement: "missing learning data is
    handled safely").

    `proposal_applier` (added alongside planning/proposal_applier.py),
    if given, must be a `ProposalApplier`. Same story as `analyzer`/
    `proposal_generator`: stored but never consulted from inside
    `run()`, and exists purely so a caller can invoke
    `apply_correction_proposal` (below) without wiring a separate
    `ProposalApplier` by hand. Omitting it is always safe *unless* a
    caller actually reaches the point of applying an already-valid
    proposal - see `apply_correction_proposal`'s own docstring for
    exactly when that raises.

    `proposal_history` (added alongside planning/proposal_history.py),
    if given, must be a `ProposalHistory`. Unlike `proposal_applier`,
    this one *is* written to from inside `apply_correction_proposal` -
    but only ever via `ProposalHistory.record`, which itself only ever
    stores a result that already reports success (see
    proposal_history.py). Omitting it (the default, `None`) is always
    safe - a successfully-applied change simply isn't recorded
    anywhere beyond the structured result `apply_correction_proposal`
    already returns.
    """

    def __init__(
        self,
        goal_manager,
        plan_manager,
        plan_execution_controller,
        goal_completion_evaluator=None,
        event_log=None,
        analyzer=None,
        proposal_generator=None,
        learning_record_store=None,
        proposal_applier=None,
        proposal_history=None,
        audit_log=None,
        version_system=None,
    ):
        if not isinstance(goal_manager, GoalManager):
            raise TypeError("AgentLoop requires a GoalManager instance.")
        if not isinstance(plan_manager, PlanManager):
            raise TypeError("AgentLoop requires a PlanManager instance.")
        if not isinstance(plan_execution_controller, PlanExecutionController):
            raise TypeError(
                "AgentLoop requires a PlanExecutionController instance."
            )
        if goal_completion_evaluator is not None and not isinstance(
            goal_completion_evaluator, GoalCompletionEvaluator
        ):
            raise TypeError(
                "AgentLoop's goal_completion_evaluator must be a "
                "GoalCompletionEvaluator instance."
            )
        if event_log is not None and not isinstance(event_log, ExecutionEventLog):
            raise TypeError("AgentLoop's event_log must be an ExecutionEventLog instance.")
        if analyzer is not None and not isinstance(analyzer, AdaptivePlanAnalyzer):
            raise TypeError("AgentLoop's analyzer must be an AdaptivePlanAnalyzer instance.")
        if proposal_generator is not None and not isinstance(proposal_generator, AdaptivePlanProposal):
            raise TypeError("AgentLoop's proposal_generator must be an AdaptivePlanProposal instance.")
        if proposal_applier is not None and not isinstance(proposal_applier, ProposalApplier):
            raise TypeError("AgentLoop's proposal_applier must be a ProposalApplier instance.")
        if proposal_history is not None and not isinstance(proposal_history, ProposalHistory):
            raise TypeError("AgentLoop's proposal_history must be a ProposalHistory instance.")
        if audit_log is not None and not isinstance(audit_log, CodeChangeAuditLog):
            raise TypeError("AgentLoop's audit_log must be a CodeChangeAuditLog instance.")
        if version_system is not None and not isinstance(version_system, VersionSystem):
            raise TypeError("AgentLoop's version_system must be a VersionSystem instance.")
        if learning_record_store is not None and not isinstance(
            learning_record_store, LearningRecordStore
        ):
            raise TypeError(
                "AgentLoop's learning_record_store must be a "
                "LearningRecordStore instance."
            )

        self._goal_manager = goal_manager
        self._plan_manager = plan_manager
        self._controller = plan_execution_controller
        self._evaluator = (
            goal_completion_evaluator
            if goal_completion_evaluator is not None
            else GoalCompletionEvaluator(goal_manager, plan_manager)
        )
        self.event_log = (
            event_log if event_log is not None else plan_execution_controller.event_log
        )
        self._analyzer = analyzer
        self._proposal_generator = proposal_generator
        self._proposal_applier = proposal_applier
        # Public, like self.event_log/self.learning_records - a
        # caller/test may inspect (never replace via a second
        # AgentLoop) the exact same history apply_correction_proposal
        # writes successful applications into. None (the default)
        # means "no history to record into" - always handled safely
        # (see apply_correction_proposal below).
        self.proposal_history = proposal_history
        # Public, like self.event_log above - a caller/test may inspect
        # (never replace via a second AgentLoop) the exact same store
        # this loop reads from. None (the default) means "no learning
        # data available" - always handled safely, never raised on
        # (see _relevant_learning_records below).
        self.learning_records = learning_record_store
        # Public, like self.event_log/self.learning_records/
        # self.proposal_history above - a caller/test may inspect
        # (never replace via a second AgentLoop) the exact same audit
        # log `record_self_upgrade_audit` below writes into. None (the
        # default) means "no audit log to record into" - always
        # handled safely (see record_self_upgrade_audit below). Never
        # a second Self-Upgrade or version system - see
        # agent/code_change_self_upgrade_audit.py's own docstring.
        self.audit_log = audit_log if audit_log is not None else CodeChangeAuditLog()
        # Public, like self.audit_log above - a caller/test may inspect
        # (never replace via a second AgentLoop) the exact same,
        # existing `self_upgrade.version_system.VersionSystem` this
        # loop's `snapshot_self_upgrade_version` below reuses.
        # Deliberately left unset (not even `None`) when no
        # version_system is supplied, same "an existing test already
        # asserts `not hasattr(self.loop, 'versions')` on a plain
        # AgentLoop" contract Prompt 350's own test suite already
        # relies on (this loop must never touch/create a version
        # system on its own) - see
        # agent/code_change_version_snapshot.py's own docstring.
        if version_system is not None:
            self.versions = version_system
        # Requirement 1, 8 (Prompt 356): one small piece of existing-
        # AgentLoop state/context - never a second AgentLoop or state
        # system - tracking exactly one CODE_CHANGE upgrade at a time.
        # Private (leading underscore), like this loop's other
        # internal bookkeeping - always read via `get_upgrade_state()`
        # below, never replaced by a second AgentLoop of its own.
        self._upgrade_state = UPGRADE_STATE_IDLE

    # ------------------------------------------------------------------
    # Event logging (requirement 15 - every iteration must be
    # observable through the existing ExecutionEventLog)
    # ------------------------------------------------------------------
    def _log_event(self, event_type, plan_id, message, data=None, severity=SEVERITY_INFO):
        """Record one AgentLoop-level ExecutionEvent through the
        existing event system (requirement: "use the existing event
        system where possible"). Never raises for a `plan_id` that
        isn't a usable string - falls back to a fixed sentinel so an
        AgentLoop-level event about an *invalid* plan_id can still be
        recorded (ExecutionEvent itself always requires a non-empty
        string plan_id - see execution_event.py)."""
        safe_plan_id = (
            plan_id if isinstance(plan_id, str) and plan_id.strip()
            else _UNKNOWN_PLAN_ID_FOR_EVENTS
        )
        event = ExecutionEvent(
            event_type=event_type,
            plan_id=safe_plan_id,
            step_id=_AGENT_STEP_ID,
            message=message,
            data=data,
            severity=severity,
        )
        return self.event_log.record(event)

    # ------------------------------------------------------------------
    # Learning (added alongside learning/execution_learning.py /
    # learning/learning_record_store.py) - read-only lookup of already-
    # stored LearningRecords relevant to one Plan, never a new learning
    # system or a new LearningRecord field.
    # ------------------------------------------------------------------
    def _relevant_learning_records(self, plan_id):
        """Every `LearningRecord` already stored in
        `self.learning_records` whose own `metadata["plan_id"]`
        matches `plan_id` exactly - the exact same `"plan_id"` key
        `ExecutionLearning.create_record` already writes into every
        record's metadata (learning/execution_learning.py) - never a
        new field, never a second store, never a new matching
        algorithm beyond this one plain equality check.

        Returns `[]` - never raises - both when this `AgentLoop` was
        constructed with no `learning_record_store` at all (`None`,
        the default) and when one exists but simply has nothing
        recorded yet for `plan_id`: "no relevant learning data" is
        always a safe, structured empty list, exactly like every
        `LearningRecordStore.find_*` method's own "safe on a miss"
        convention.

        Purely observational: never mutates a stored record (each
        entry here is already a `copy.deepcopy` courtesy of
        `LearningRecordStore.get_all`, so a caller mutating what this
        returns can never corrupt the store itself), and never
        decides or changes anything about the Plan/Goal - `run()`
        below only ever exposes this list through its own result, it
        never branches its execution decisions on it (requirement:
        "do not automatically modify the plan based on learning
        yet")."""
        if self.learning_records is None:
            return []
        return [
            record for record in self.learning_records.get_all()
            if record.metadata.get("plan_id") == plan_id
        ]

    # ------------------------------------------------------------------
    # Result shaping
    # ------------------------------------------------------------------
    @staticmethod
    def _merge(target_list, source_list):
        """Append every item of `source_list` onto `target_list` that
        isn't already present, preserving order and never duplicating
        an entry already recorded - same "accumulate without
        duplicating" convention `PlanExecutionController.execute_plan`
        already applies to its own `warnings` list."""
        for item in source_list:
            if item not in target_list:
                target_list.append(item)

    # ------------------------------------------------------------------
    # Connect execution output back into AgentLoop state (Prompt 313):
    # a completed step's own, already-existing `ExecutionResult`
    # output - reached here exactly as `PlanExecutionController.
    # execute_plan` already returns it (`outputs`/`execution_ids`/
    # `completed_steps`, themselves built unchanged from
    # `StepExecutionController.execute_step`'s own per-step
    # `ExecutionResult` - never a second, disagreeing copy of any of
    # that) - made available, keyed by `step_id` and carrying its own
    # `execution_id`, to the next pass of `run()`'s own `while` loop.
    # Purely bookkeeping: never executes anything itself, never
    # invents/transforms a value, and is never consulted by `run()` to
    # decide whether to keep going (that remains entirely
    # `GoalCompletionEvaluator`/`PlanExecutionController`'s job,
    # unchanged) - only ever exposed, unmodified, through the result
    # dict `_result` below shapes (requirement: "do not create a new
    # memory or learning system").
    # ------------------------------------------------------------------
    @staticmethod
    def _step_execution_outputs(exec_result):
        """Every step this one `PlanExecutionController.execute_plan`
        call itself completed successfully, as
        `{step_id: {"step_id", "execution_id", "output"}}` - the exact
        `output` and `execution_id` `exec_result` already carries for
        that step (from `exec_result["outputs"]`/`exec_result
        ["execution_ids"]`, the latter aligned position-by-position
        with `exec_result["executed_steps"]` - see
        `PlanExecutionController.execute_plan`'s own docstring),
        neither value ever re-derived, copied-with-changes, or
        otherwise transformed here.

        Only a step present in `exec_result["completed_steps"]`
        contributes an entry - a FAILED (or otherwise not-completed)
        step is never included, exactly mirroring the same
        `completed_steps`/`outputs` split `PlanExecutionController.
        execute_plan` itself already returns (its own `outputs` dict
        is already scoped to completed steps only - see that method's
        docstring - so this is a read of that same guarantee, never a
        second, disagreeing success check). A completed step that
        produced no output (not present in `exec_result["outputs"]`)
        is skipped as well - never inventing a placeholder output for
        it.

        Never mutates `exec_result` or anything reachable from it."""
        completed = set(exec_result["completed_steps"])
        execution_ids_by_step = dict(
            zip(exec_result["executed_steps"], exec_result["execution_ids"])
        )
        entries = {}
        for step_id, output in exec_result["outputs"].items():
            if step_id not in completed:
                continue
            entries[step_id] = {
                "step_id": step_id,
                "execution_id": execution_ids_by_step.get(step_id),
                "output": output,
            }
        return entries

    def _result(
        self, success, goal_id, plan_id, status, iterations, goal_status,
        executed_steps, completed_steps, failed_steps, blocked_steps,
        outputs, evidence, warnings, error, learning_context, next_step,
        step_outputs=None,
    ):
        """The one place that shapes a `run()` return value, so every
        path below - invalid input, an already-satisfied Goal, a clean
        multi-iteration run, a failure, a blocked stop, an exhausted
        iteration budget - comes back in exactly the same structured
        shape (requirement 7).

        `learning_context` is always a plain list of
        `LearningRecord.to_dict()` dicts (never None, never a bare
        `LearningRecord` object) - same "plain, JSON-shaped result"
        convention this dict's every other field already follows.

        `next_step` (added alongside `_identify_next_step` below) is
        always either `None` or a plain, JSON-shaped dict - never a
        raw `PlanStep` object - same convention.

        `step_outputs` (added alongside `_step_execution_outputs`
        above - Prompt 313) is always a plain
        `{step_id: {"step_id", "execution_id", "output"}}` dict -
        `{}` (never `None`) when omitted, e.g. for every "before a
        single step could ever run" outcome (`_fail_invalid`, or a
        `run()` iteration that stops before its own execution step -
        see requirements b/c above `run()`'s own loop). Purely
        additive: the existing `outputs` field above (`{step_id:
        output}`) is completely unchanged by this - a caller that
        never looks at `step_outputs` sees exactly the same result
        shape this method has always returned."""
        return {
            "success": bool(success),
            "goal_id": goal_id,
            "plan_id": plan_id,
            "status": status,
            "iterations": iterations,
            "goal_status": goal_status,
            "executed_steps": list(executed_steps),
            "completed_steps": list(completed_steps),
            "failed_steps": list(failed_steps),
            "blocked_steps": list(blocked_steps),
            "outputs": dict(outputs),
            "step_outputs": dict(step_outputs) if step_outputs else {},
            "evidence": list(evidence),
            "warnings": list(warnings),
            "error": error,
            "learning_context": [record.to_dict() for record in learning_context],
            "next_step": next_step,
        }

    def _fail_invalid(self, goal_id, plan_id, message):
        """Shared path for every "before a single iteration could
        start" guard failure (requirements 1, 2): unknown goal_id,
        unknown plan_id, or a Plan that doesn't belong to this Goal.
        Logs `EVENT_AGENT_LOOP_FAILED` and returns the same structured
        shape every other outcome does, with `iterations=0` (nothing
        was ever evaluated or executed), `learning_context=[]`
        (this Plan was never confirmed valid, so there is nothing
        real to relate any learning record to), and `next_step=None`
        (same reason - a `plan_id` that was never confirmed to name a
        real, matching Plan is never handed to
        `PlanExecutionCoordinator.get_next_ready_step` either)."""
        self._log_event(
            EVENT_AGENT_LOOP_FAILED, plan_id, message,
            data={"goal_id": goal_id, "plan_id": plan_id, "status": STATUS_INVALID},
            severity=SEVERITY_ERROR,
        )
        return self._result(
            False, goal_id, plan_id, STATUS_INVALID, 0, STATE_UNKNOWN,
            [], [], [], [], {}, [], [], message, [], None,
        )

    # ------------------------------------------------------------------
    # Next-step lookahead (Prompt 309: connect the existing AgentLoop to
    # the existing PlanExecutionCoordinator) - read-only, never executes
    # anything.
    # ------------------------------------------------------------------
    def _identify_next_step(self, plan_id):
        """When the current Goal is *not* satisfied, ask the existing
        `PlanExecutionCoordinator.get_next_ready_step` (reused
        unchanged - never re-derived here) which step, if any, is both
        currently STATUS_READY and actually executable right now, and
        report that as plain, JSON-shaped data.

        Reuses the exact same `PlanExecutionCoordinator` instance
        `self._controller` (this `AgentLoop`'s own
        `PlanExecutionController`) already calls `get_next_ready_step`
        on internally during `execute_plan` - via the controller's
        public `coordinator` property - so "what would run next" is
        always asked against the exact same `PlanManager`,
        `CapabilityHandlerRegistry`, and `ExecutableCapabilityRegistry`
        the actual execution stack uses, never a second, disagreeing
        coordinator built with different registries.

        Purely a read-only lookahead: never calls a handler or a
        capability, never writes a PlanStep's status, never creates a
        new PlanStep, and never modifies the Plan in any way - exactly
        as `PlanExecutionCoordinator.get_next_ready_step` itself
        already guarantees (see execution/plan_execution_coordinator.py's
        module docstring). Crucially, this method never executes the
        step it identifies - identifying the next step and running it
        remain two entirely separate operations; running it is still
        only ever done via `PlanExecutionController.execute_plan`,
        called elsewhere in `run()`'s own loop, on a *later* iteration.

        Respects the exact same dependency/status check
        (`PlanStep.status == STATUS_READY`) and capability/handler
        readiness check `get_next_ready_step` already applies - a
        BLOCKED step (unresolved dependency) is never even considered,
        and a READY step missing a required capability or handler is
        skipped, exactly as `get_next_ready_step` already does; this
        method never re-derives either check.

        Returns a plain dict:
            {
                "step_id": step_id or None,  # the chosen step, if any
                "executable": bool,          # True only when a step
                                              # was actually found
                "reason": str,               # why this step was
                                              # chosen, or why none was
                "warnings": [str, ...],      # one entry per READY step
                                              # skipped before this
                                              # result, explaining why
            }
        Deliberately drops `get_next_ready_step`'s own raw `"step"`
        (a `PlanStep` object) - this result stays plain/JSON-shaped,
        same convention as every other field `run()` returns; a caller
        that wants the actual `PlanStep` object can still look it up
        via `PlanManager.get_plan(plan_id)` using `"step_id"`."""
        next_result = self._controller.coordinator.get_next_ready_step(plan_id)
        return {
            "step_id": next_result["step_id"],
            "executable": bool(next_result["executable"]),
            "reason": next_result["reason"],
            "warnings": list(next_result["warnings"]),
        }

    # ------------------------------------------------------------------
    # Connect next-step selection to controlled execution (Prompt 310:
    # connect the existing AgentLoop next-step selection to controlled
    # step execution) - reuses `_identify_next_step` above (itself
    # already built on the existing `PlanExecutionCoordinator`, shared
    # unchanged via `self._controller.coordinator`) to select, and, only
    # if that selection is a valid READY, executable step, runs exactly
    # that one step through the existing `StepExecutionController`
    # (shared unchanged via `self._controller.step_controller`) -
    # `execute_step` is the single, already-existing place a step is
    # prepared, actually run, and its `ExecutionResult`/history/event-
    # log recording and COMPLETED/FAILED status transition happen;
    # never a second, disagreeing copy of any of that.
    # ------------------------------------------------------------------
    def execute_next_step(self, plan_id, capability_system=None):
        """Identify the next READY, executable step for `plan_id` (via
        `_identify_next_step`, read-only) and, if one was found, run
        exactly that one step - never more than one - through the
        existing `StepExecutionController.execute_step`, unchanged.

        This is a separate, explicitly-invoked action - never called
        automatically from `run()` itself (`run()`'s own bounded loop
        continues to drive whole-plan execution via the existing
        `PlanExecutionController.execute_plan`, exactly as before this
        method existed - this method never replaces or duplicates that
        path). A caller wanting single-step-at-a-time control over an
        already-identified next step calls this method directly.

        Never executes a second step in the same call: a BLOCKED step
        (unresolved dependency), a step missing a required capability
        or registered handler, or "nothing left to do" all result in
        `executed=False` and no call to `StepExecutionController.
        execute_step` at all - the exact same READY/executable checks
        `PlanExecutionCoordinator.get_next_ready_step` already applies,
        never re-derived here. Implements no automatic retry of its
        own: a step that has already FAILED is no longer STATUS_READY,
        so it is never selected again by a later call to this method,
        exactly as `PlanExecutionController.execute_plan` itself
        already guarantees for its own per-step loop.

        Creates no new `PlanStep`, no new capability, and no new
        handler - only a step/capability/handler a caller already
        registered ahead of time can ever run here.

        Returns a plain dict:
            {
                "executed": bool,             # True only when a step
                                               # was actually run
                "step_id": str or None,       # the selected step, if
                                               # any (even when not
                                               # executed, e.g. a
                                               # step_id that turned
                                               # out to be BLOCKED is
                                               # never returned here -
                                               # only ever None or an
                                               # executable step_id,
                                               # exactly as
                                               # `_identify_next_step`
                                               # already reports it)
                "success": bool or None,      # None when nothing was
                                               # executed; otherwise the
                                               # existing
                                               # StepExecutionController.
                                               # execute_step's own
                                               # "success"
                "execution_result": dict or None,  # the existing,
                                               # unmodified structured
                                               # result
                                               # `StepExecutionController.
                                               # execute_step` already
                                               # returns, or None when
                                               # nothing was executed
                "reason": str,                # why this step was
                                               # selected, or why none
                                               # was (from
                                               # `_identify_next_step`)
                "warnings": [str, ...],       # from the selection, and
                                               # (when a step was
                                               # executed) from
                                               # `execute_step` as well
            }
        """
        # Same one-time refresh `PlanExecutionController.execute_plan`
        # itself already performs before its own loop starts (see
        # execute_plan's own "Step 1"), reused unchanged here so a
        # PENDING step whose dependencies already resolved is
        # correctly classified as READY/BLOCKED before selection -
        # never a second, disagreeing readiness computation. Skipped
        # for an unknown plan_id (same "never raise for a bad id"
        # convention `_identify_next_step`/`get_next_ready_step`
        # already follow) - `_identify_next_step` below still reports
        # a structured "not executable" result for it.
        if self._plan_manager.get_plan(plan_id) is not None:
            self._plan_manager.refresh_plan_step_statuses(plan_id, capability_system)

        next_step = self._identify_next_step(plan_id)
        step_id = next_step["step_id"]
        warnings = list(next_step["warnings"])

        if not next_step["executable"] or step_id is None:
            self._log_event(
                EVENT_AGENT_EXECUTION_COMPLETED, plan_id,
                f"No READY, executable step selected: {next_step['reason']}.",
                data={
                    "executed": False, "step_id": None,
                    "reason": next_step["reason"],
                },
            )
            return {
                "executed": False,
                "step_id": None,
                "success": None,
                "execution_result": None,
                "reason": next_step["reason"],
                "warnings": warnings,
            }

        # Exactly one call, to the existing, unchanged
        # StepExecutionController - never a second copy of preparation
        # or capability-execution logic, and never another step
        # executed within this same call.
        exec_result = self._controller.step_controller.execute_step(
            plan_id, step_id, capability_system=capability_system,
        )
        self._merge(warnings, exec_result["warnings"])

        self._log_event(
            EVENT_AGENT_EXECUTION_COMPLETED, plan_id,
            f"Selected step executed: {step_id} "
            f"({'succeeded' if exec_result['success'] else 'failed'}).",
            data={
                "executed": True, "step_id": step_id,
                "success": exec_result["success"],
            },
            severity=SEVERITY_INFO if exec_result["success"] else SEVERITY_ERROR,
        )

        return {
            "executed": True,
            "step_id": step_id,
            "success": exec_result["success"],
            "execution_result": exec_result,
            "reason": next_step["reason"],
            "warnings": warnings,
        }

    def execute_routed_step(self, declaration=None, legacy_input=None, tool_input=None,
                            capability_system=None, tool_registry=None):
        """Explicitly-invoked, additive routed entry point (Prompt 719-C, Section 6). Never called from `run()`.

        `declaration`, `legacy_input` and `tool_input` are caller-owned and go unchanged to
        `resolve_tool_step_dispatch` (Prompt 716 route + Prompt 717 payload selection), called exactly once.
          - Anything but an explicit valid "section6_tool" resolves to the legacy route (Prompt 716 fallback):
            `legacy_input` must be {"plan_id": <non-blank str>} and the existing `execute_next_step(plan_id,
            capability_system)` is called once, unchanged.
          - An explicit "section6_tool" route validates `tool_input` with `build_tool_step_intent` (Prompt 719-A), takes
            the Plan from this loop's own `PlanManager.get_plan(plan_id)` (None is passed on; the runner rejects it), uses
            the caller-supplied `tool_registry`, and calls `run_tool_step_intent` (Prompt 719-B) exactly once.
        Every rejection or failure on the Section 6 route is returned as is: it never reaches `execute_next_step`, and
        nothing is caught here. No authorization, retry, capability mapping or ToolRequest logic lives in this method.

        Returns a fresh plain dict: route, explicit, fallback, route_code, dispatch_status, dispatch_code, stage
        ("dispatch" | "payload" | "execution"), status ("rejected" = nothing was handed to the selected
        route's executor; otherwise the legacy status, or "completed"/"failed" from the runner's `ok`), error_code,
        failures, legacy_result (the unchanged `execute_next_step` dict, else None), tool_result (the runner result's
        `to_dict()`, else None). At most one of legacy_result / tool_result is ever populated.

        ROUTE PIN (Prompt 719-D): this loop keeps a private, in-memory {plan_id: route} map that lives and dies with this AgentLoop
        instance (never persisted, never global, never written to Plan / PlanStep / PlanManager). The first Section 6 execution of a plan
        pins it to "section6_tool" once the route is accepted (intent valid, plan known); the first explicitly declared legacy execution
        of a known plan pins it to "legacy_capability". A plan that already has a pin can only be executed again through the same
        route: any other route is rejected before anything runs (stage "route_pin", error_code "ROUTE_PIN_CONFLICT"), so a plan never
        silently switches routes. Rejections create no pin. Undeclared (fallback) legacy calls are checked against an existing pin
        but never create one. `execute_next_step` and `run` called directly neither read nor write the pin.
        """
        dispatch = resolve_tool_step_dispatch(declaration, legacy_input, tool_input)
        pins = self.__dict__.setdefault("_plan_route_pins", {})

        def envelope(stage, status, error_code, failures=None, legacy_result=None, tool_result=None):
            return {
                "route": dispatch.route, "explicit": dispatch.explicit, "fallback": dispatch.fallback,
                "route_code": dispatch.route_code, "dispatch_status": dispatch.dispatch_status,
                "dispatch_code": dispatch.dispatch_code, "stage": stage, "status": status,
                "error_code": error_code, "failures": list(failures or []),
                "legacy_result": legacy_result, "tool_result": tool_result,
            }

        if dispatch.is_rejected:
            return envelope("dispatch", "rejected", dispatch.dispatch_code)

        payload = dispatch.payload
        if not dispatch.is_section6_tool:
            plan_id = payload.get("plan_id") if isinstance(payload, dict) and list(payload) == ["plan_id"] else None
            if not isinstance(plan_id, str) or not plan_id.strip():
                return envelope("payload", "rejected", "LEGACY_INPUT_INVALID")
            if pins.get(plan_id, dispatch.route) != dispatch.route:
                return envelope("route_pin", "rejected", "ROUTE_PIN_CONFLICT")
            if dispatch.explicit and self._plan_manager.get_plan(plan_id) is not None:
                pins[plan_id] = dispatch.route
            legacy = self.execute_next_step(plan_id, capability_system)
            return envelope("execution", "executed" if legacy["executed"] else "not_executed", None, legacy_result=legacy)

        intent = build_tool_step_intent(payload)
        if not intent.ok:
            return envelope("payload", "rejected", "SECTION6_INTENT_REJECTED", failures=intent.failures)

        if pins.get(intent.plan_id, dispatch.route) != dispatch.route:
            return envelope("route_pin", "rejected", "ROUTE_PIN_CONFLICT")
        plan = self._plan_manager.get_plan(intent.plan_id)
        if plan is not None:
            pins[intent.plan_id] = dispatch.route
        run = run_tool_step_intent(intent, plan, tool_registry)
        return envelope("execution", "completed" if run.ok else "failed", None if run.ok else "SECTION6_RUN_NOT_OK",
                        failures=run.failures, tool_result=run.to_dict())

    def _finish(
        self, success, status, goal_id, plan_id, iterations, goal_status,
        executed_steps, last_evaluation, outputs, evidence, warnings, error, message,
        learning_context, step_outputs=None,
    ):
        """Shared path for every outcome reached *after* at least one
        evaluation happened: logs the matching AgentLoop-level
        "we are stopping now" event and shapes the final result,
        deriving `completed_steps`/`failed_steps`/`blocked_steps` from
        `last_evaluation` (the most recent `GoalCompletionEvaluator.
        evaluate` result) - the same step-classification
        `GoalCompletionEvaluator` itself already computes, never
        re-derived here.

        Also identifies (never executes) the next READY step via
        `_identify_next_step` above, but only when the Goal is *not*
        satisfied (`status != STATUS_SATISFIED`) - a satisfied Goal
        never needs, and never gets, another step selected, since
        `run()` itself already stops without executing anything once
        the Goal is satisfied.

        `step_outputs` (Prompt 313) is passed straight through to
        `_result` unchanged - see `_step_execution_outputs`/`_result`
        above; omitted (`None`) for every outcome reached before this
        run's own execution step ever happened."""
        completed_steps = list(last_evaluation["completed_steps"]) if last_evaluation else []
        failed_steps = list(last_evaluation["failed_steps"]) if last_evaluation else []
        blocked_steps = list(last_evaluation["blocked_steps"]) if last_evaluation else []

        next_step = (
            None if status == STATUS_SATISFIED else self._identify_next_step(plan_id)
        )

        if status == STATUS_SATISFIED:
            event_type = EVENT_AGENT_LOOP_COMPLETED
            severity = SEVERITY_INFO
        elif status in _FAILURE_STATUSES:
            event_type = EVENT_AGENT_LOOP_FAILED
            severity = SEVERITY_ERROR
        else:
            event_type = EVENT_AGENT_LOOP_STOPPED
            severity = SEVERITY_INFO

        self._log_event(
            event_type, plan_id, message,
            data={
                "goal_id": goal_id, "plan_id": plan_id, "status": status,
                "iterations": iterations, "goal_status": goal_status, "success": success,
            },
            severity=severity,
        )

        return self._result(
            success, goal_id, plan_id, status, iterations, goal_status,
            executed_steps, completed_steps, failed_steps, blocked_steps,
            outputs, evidence, warnings, error, learning_context, next_step,
            step_outputs=step_outputs,
        )

    # ------------------------------------------------------------------
    # Adaptive plan analysis (requirement: "AgentLoop may request
    # analysis when the Goal is not satisfied" - added alongside
    # planning/adaptive_plan_analyzer.py)
    # ------------------------------------------------------------------
    def request_analysis(self, goal_id, plan_id):
        """Ask this loop's `AdaptivePlanAnalyzer` (see `analyzer` in
        `__init__`) why `plan_id` has not satisfied `goal_id`, and
        return its structured analysis result unchanged.

        This is purely an analysis step, exactly as
        `AdaptivePlanAnalyzer.analyze` itself already is: read-only,
        never executes a step or a capability, never modifies the Goal
        or the Plan, and never decides or triggers the next action -
        that decision remains entirely the caller's (or a future
        `run()` call's) to make, never this method's or the
        analyzer's. `run()` itself never calls this automatically; a
        caller typically calls this only after `run()` reports a
        `status` other than `STATUS_SATISFIED`.

        Raises ValueError if no `analyzer` was supplied to this
        `AgentLoop` - same "never silently do nothing" convention the
        rest of this project's optional-collaborator checks already
        follow (see e.g. `PlanManager.check_plan_capabilities`
        requiring an explicit `capability_system`)."""
        if self._analyzer is None:
            raise ValueError(
                "AgentLoop.request_analysis requires this AgentLoop to have "
                "been constructed with an AdaptivePlanAnalyzer (see the "
                "analyzer argument to __init__)."
            )
        return self._analyzer.analyze(goal_id, plan_id)

    def request_proposal(self, goal_id, plan_id):
        """Ask this loop's `AdaptivePlanProposal` (see
        `proposal_generator` in `__init__`) what, if anything, could
        safely be changed about `plan_id` to help satisfy `goal_id`,
        and return its structured proposal result unchanged.

        Exactly as read-only, analysis-only a step as `request_analysis`
        above: never modifies the Goal or the Plan, never executes a
        step or a capability, and - critically - never applies the
        proposal it returns. Applying a proposed change remains a
        separate, explicitly-invoked, not-yet-built step; this method
        only ever hands the caller (or a future `run()` call) the
        proposal to look at, never a way to act on it from here.
        `run()` itself never calls this automatically; a caller
        typically calls this only after `run()` reports a `status`
        other than `STATUS_SATISFIED` - most usefully after first
        calling `request_analysis` to see why.

        Raises ValueError if no `proposal_generator` was supplied to
        this `AgentLoop` - same convention `request_analysis` already
        follows for a missing `analyzer`."""
        if self._proposal_generator is None:
            raise ValueError(
                "AgentLoop.request_proposal requires this AgentLoop to have "
                "been constructed with an AdaptivePlanProposal (see the "
                "proposal_generator argument to __init__)."
            )
        return self._proposal_generator.propose(goal_id, plan_id)

    # ------------------------------------------------------------------
    # Test result evaluation (connects the existing `python_test_runner`
    # capability's structured result - execution/
    # python_test_runner_capability.py - to this loop's own context via
    # agent/test_result_evaluation.py's `build_test_evaluation`, reused
    # unchanged rather than a second, differently-behaving classifier)
    # ------------------------------------------------------------------
    def evaluate_test_result(self, test_result):
        """Classify an already-produced `python_test_runner` capability
        result (e.g. read from a completed step's own output - see
        `run()`'s `outputs`/`step_outputs` result fields, or a direct
        `ExecutionEngine.execute_registered_capability("python_test_runner",
        ...)` call's `.output`) into exactly one of `PASSED`/`FAILED`/
        `TIMEOUT`/`INVALID`, and expose that alongside the original
        result as one small, structured dict.

        Reuses `agent.test_result_evaluation.build_test_evaluation`
        (itself built on `classify_test_result`) completely unchanged -
        this method adds no classification logic of its own, it only
        makes that existing, standalone classifier reachable as part of
        this loop's own context, the same way `request_analysis`/
        `request_proposal` above make `AdaptivePlanAnalyzer`/
        `AdaptivePlanProposal` reachable. Unlike those two, this method
        needs no optional collaborator to have been supplied to
        `__init__` - `classify_test_result` is a pure, stateless
        function, so `evaluate_test_result` is always available on
        every `AgentLoop`, with no `ValueError` guard for a missing
        collaborator.

        Purely a read-only classification step: never re-runs the
        tests, never retries anything, never touches a source file,
        and never executes a capability, step, or Plan of its own -
        it only reads the `success`/`timed_out` fields already present
        in `test_result` (see `classify_test_result`'s own docstring
        for the exact, fixed rules). `run()` itself never calls this
        automatically - same "explicitly invoked by a caller, never
        triggered by run() on its own initiative" convention
        `request_analysis`/`request_proposal` already follow.

        Never raises: an input that isn't a real `python_test_runner`
        result (missing fields, wrong types, `None`, ...) is reported
        as `"classification": "INVALID"`, exactly as
        `classify_test_result` itself already guarantees, never an
        exception propagating out of this method."""
        return build_test_evaluation(test_result)

    def evaluate_correction_decision(self, test_result):
        """Take an already-produced `python_test_runner` capability
        result - the same input `evaluate_test_result` above accepts -
        and expose the small, structured "does this call for a
        correction" decision built on top of that same evaluation.

        Reuses `agent.test_result_evaluation.build_correction_decision`
        completely unchanged, which itself reuses
        `build_test_evaluation`/`classify_test_result` completely
        unchanged - this method adds no classification or decision
        logic of its own, it only makes that existing, standalone
        decision reachable as part of this loop's own context, the
        same way `evaluate_test_result` above does for the plain
        evaluation. Needs no optional collaborator to have been
        supplied to `__init__`, exactly like `evaluate_test_result`.

        Always returns
        `{"correction_required": <bool>, "reason": <"PASSED"|"FAILED"|
        "TIMEOUT"|"INVALID">, "evaluation": <the exact dict
        evaluate_test_result(test_result) itself would return>}`:
        `correction_required` is `False` only for `"PASSED"`, and `True`
        for `"FAILED"`, `"TIMEOUT"`, or `"INVALID"` - see
        `is_correction_required`'s own docstring in
        `test_result_evaluation.py` for the exact, fixed rule. The
        original evaluation - classification together with the exact
        `test_result` it was derived from - is preserved completely
        unmodified under `"evaluation"`.

        A read-only decision step, not a new planning system and not a
        retry mechanism: it never modifies a file, never runs or
        re-runs a test, never executes a capability, step, or Plan of
        its own, and never automatically retries or triggers another
        step - it only reports a structured decision for a caller to
        act on explicitly. `run()` itself never calls this
        automatically, same "explicitly invoked by a caller" convention
        `evaluate_test_result`/`request_analysis`/`request_proposal`
        already follow.

        Never raises: exactly like `evaluate_test_result`, a malformed
        `test_result` is reported as `"reason": "INVALID"`,
        `"correction_required": True`, never an exception propagating
        out of this method."""
        return build_correction_decision(test_result)

    # ------------------------------------------------------------------
    # Code change evaluation (Prompt 331: connect the existing
    # `code_change_apply_and_test` capability's own structured result -
    # execution/code_change_apply_and_test_capability.py - to this
    # loop's own context via agent/code_change_evaluation.py's
    # `build_code_change_evaluation`, reused unchanged rather than a
    # second, differently-behaving classifier)
    # ------------------------------------------------------------------
    def evaluate_code_change_result(self, code_change_result):
        """Classify an already-produced `code_change_apply_and_test`
        capability result (e.g. read from a completed step's own
        output - see `run()`'s `outputs`/`step_outputs` result fields,
        or a direct `ExecutionEngine.execute_registered_capability(
        "code_change_apply_and_test", ...)` call's `.output`) into one
        small, structured state this loop can act on, distinguishing:

          - the change succeeded and the test passed
          - the change succeeded but the test failed
          - the change itself failed (no test was ever run)
          - the test timed out
          - an invalid/unrecognised operation

        Reuses `agent.code_change_evaluation.build_code_change_evaluation`
        completely unchanged - this method adds no classification logic
        of its own, it only makes that existing, standalone classifier
        reachable as part of this loop's own context, the same way
        `evaluate_test_result` above does for a bare `python_test_runner`
        result. Needs no optional collaborator to have been supplied to
        `__init__` - `build_code_change_evaluation` is a pure, stateless
        function, so this method is always available on every
        `AgentLoop`.

        Always returns
        `{"state", "change_status", "test_status",
        "correction_required", "error", "change_result", "test_result"}`
        exactly as `build_code_change_evaluation` itself already shapes
        it - see that function's own docstring for the precise, fixed
        rules, including `correction_required` being `True` only when
        the final test status is FAILED or TIMEOUT, and the original
        `change_result`/`test_result` always being preserved separately,
        completely unmodified.

        Purely a read-only classification step: never re-applies a
        change, never re-runs a test, never retries anything, and never
        executes a capability, step, or Plan of its own. `run()` itself
        never calls this automatically, and this method never performs
        another correction or modifies the Plan on its own - same
        "explicitly invoked by a caller, no automatic follow-up action"
        convention `evaluate_test_result`/`evaluate_correction_decision`
        above already follow.

        Never raises: an input that isn't a real
        `code_change_apply_and_test` result is reported as
        `"state": "INVALID"`, `"correction_required": False`, never an
        exception propagating out of this method."""
        return build_code_change_evaluation(code_change_result)

    def evaluate_capability_test_result(self, capability_test_result):
        """Evaluate an already-produced `CapabilityTestResult` (what
        `self_upgrade.capability_test_execution.run_capability_tests`
        returns, Prompt 366) into a structured
        `CapabilityEvaluationResult`, reusing
        `self_upgrade.capability_evaluation.evaluate_capability_test_result`
        completely unchanged. Pure and read-only: never corrects,
        retries, re-runs tests, modifies files, or registers/activates
        anything; `run()` never calls it automatically. Never raises."""
        return _evaluate_capability_test_result(capability_test_result)

    def analyze_capability_correction(self, evaluation_result, allowed_dirs=None):
        """Route an already-produced `CapabilityEvaluationResult`
        (Prompt 366) through the existing error-analysis, correction
        proposal and proposal-validation steps (Prompt 367), reusing
        `self_upgrade.capability_correction_analysis.
        build_capability_correction_analysis` unchanged. This loop's
        own `retrieve_successful_correction_patterns` supplies the
        same advisory `learned_patterns` `propose_code_correction`
        uses. Read-only: never applies a correction, retries, executes
        code, modifies files, or registers anything; `run()` never
        calls it. Never raises."""
        return _build_capability_correction_analysis(
            evaluation_result, allowed_dirs=allowed_dirs,
            learned_patterns_provider=self.retrieve_successful_correction_patterns,
        )

    def apply_capability_correction(self, correction_analysis, changes,
                                    allowed_dirs=None, protected_paths=None):
        """Apply exactly one caller-supplied source change to the
        failed capability a READY_FOR_CORRECTION
        `CapabilityCorrectionAnalysisResult` (Prompt 367) identifies
        (Prompt 368), reusing `self_upgrade.capability_correction_apply.
        apply_capability_correction` unchanged - which itself reuses the
        existing proposal validation, code_change_apply/text_file_edit
        and AST validation. Never retests, retries, executes code, or
        registers anything; `run()` never calls it. Never raises."""
        return _apply_capability_correction(
            correction_analysis, changes,
            allowed_dirs=allowed_dirs, protected_paths=protected_paths,
        )

    def verify_capability_correction(self, previous_test_result, correction_apply_result,
                                     project_dir, test_target, allowed_dirs=None,
                                     timeout_seconds=None):
        """Retest a capability once after an APPLIED correction
        (Prompt 368) and compare with the previous failure (Prompt
        369), reusing `self_upgrade.capability_correction_verification.
        verify_capability_correction` unchanged - which itself reuses
        `run_capability_tests` and `evaluate_capability_test_result`.
        Never applies another correction, retries, registers or
        activates anything; `run()` never calls it. Never raises."""
        return _verify_capability_correction(
            previous_test_result, correction_apply_result, project_dir, test_target,
            allowed_dirs=allowed_dirs, timeout_seconds=timeout_seconds,
        )

    def evaluate_self_upgrade_approval_gate(self, human_approval_request, approval_manager):
        """Read-only continuation gate for a capability's approval
        state (Prompt 372), reusing `self_upgrade.
        capability_approval_gate.evaluate_self_upgrade_approval_gate`
        unchanged - which itself re-checks a PENDING_APPROVAL request
        against the supplied `approval_manager` (self_upgrade.
        capability_approval_manager.ApprovalManager, Prompt 371) rather
        than trusting the request's own, possibly-stale status. Never
        approves, rejects, activates, registers, or creates a version
        snapshot; `run()` never calls it. Never raises."""
        return _evaluate_self_upgrade_approval_gate(human_approval_request, approval_manager)

    def prepare_capability_registration(self, human_approval_request, approval_manager,
                                        build_spec, purpose=None):
        """Prepare - never perform - the registry entry for a capability
        whose human approval was explicitly confirmed (Prompt 373),
        reusing `self_upgrade.capability_registration_preparation.
        prepare_capability_registration` unchanged - which itself
        decides approval only through the existing approval gate
        (Prompt 372). Returns a `CapabilityRegistrationPreparation`
        (BLOCKED / INVALID / READY_FOR_REGISTRATION). Never registers,
        activates, or executes a capability, never modifies source, and
        never creates a version snapshot; `run()` never calls it. Never
        raises."""
        return _prepare_capability_registration(
            human_approval_request, approval_manager, build_spec, purpose=purpose,
        )

    def build_capability_registration_plan(self, registration_preparation,
                                           approval_manager=None):
        """Describe - never perform - what a future, explicitly approved
        registration would register (Prompt 374), reusing
        `self_upgrade.capability_registration_plan.
        build_capability_registration_plan` unchanged. Only a
        READY_FOR_REGISTRATION `CapabilityRegistrationPreparation`
        (Prompt 373) can yield a READY_FOR_APPROVED_REGISTRATION plan;
        a plan is never permission to register. Never registers,
        activates, or executes a capability, never modifies source, and
        never creates a version snapshot; `run()` never calls it. Never
        raises."""
        return _build_capability_registration_plan(
            registration_preparation, approval_manager=approval_manager,
        )

    def request_capability_registration_approval(self, registration_plan):
        """Build a PENDING_APPROVAL registration approval request from a
        READY_FOR_APPROVED_REGISTRATION `CapabilityRegistrationPlan`
        (Prompt 375), reusing `self_upgrade.
        capability_registration_approval.
        request_capability_registration_approval` unchanged. The
        request only asks a human to decide: it is not stored, approved,
        or acted on here (store it with the existing `ApprovalManager.
        create_request`; only `ApprovalManager.approve` can approve
        it). Never registers, activates, or executes a capability,
        never modifies source, and never creates a version snapshot;
        `run()` never calls it. Never raises."""
        return _request_capability_registration_approval(registration_plan)

    def get_capability_lifecycle_decision(
        self, capability_name, build_result=None, apply_request=None, test_evaluation=None,
        human_approval_request=None, approval_manager=None, approval_request_id=None,
        registration_request_id=None, registration_plan=None, registration_result=None,
        verification_result=None, rollback_result=None,
    ):
        """Inspect the current Self-Upgrade lifecycle state of a
        capability (Prompt 379: `self_upgrade.capability_lifecycle.
        build_capability_lifecycle_state`, reused unchanged) and map
        it onto the one fixed, structured `CapabilityLifecycleDecision`
        this loop is allowed to report about what is currently allowed
        to happen next (Prompt 380: `self_upgrade.
        capability_lifecycle_decision.build_capability_lifecycle_decision`,
        reused unchanged). See both modules' own docstrings for the
        full status/decision vocabulary and the fixed derivation/
        mapping rules.

        This is a read-only inspection, exactly like every other
        Self-Upgrade wrapper method on this loop
        (evaluate_self_upgrade_approval_gate,
        prepare_capability_registration, etc. above): it never
        activates a capability, never executes one (or any generated
        code), never approves, rejects, registers, or modifies
        anything in the live Capability Registry, and never infers a
        human decision - a PENDING_APPROVAL lifecycle always yields
        WAITING_FOR_APPROVAL here, never anything else, and an
        APPROVED / READY_FOR_REGISTRATION lifecycle never causes a
        registration, and a REGISTERED lifecycle never causes an
        activation or execution. `run()` never calls this method, and
        calling it never changes anything this loop, `ApprovalManager`,
        or `CapabilitySystem` already store. Never raises.

        Every argument except `capability_name` is optional and is
        passed straight through to `build_capability_lifecycle_state`
        unchanged - see that function's own docstring for what each
        one is and which stage's result it expects.

        Always returns a `CapabilityLifecycleDecision` dict with
        exactly: capability_name, lifecycle_status, decision (one of
        `self_upgrade.capability_lifecycle_decision.
        ALL_CAPABILITY_DECISIONS`), reason, errors, lifecycle_state
        (the full `CapabilityLifecycleState` this decision was derived
        from, unchanged).
        """
        lifecycle_state = _build_capability_lifecycle_state(
            capability_name, build_result=build_result, apply_request=apply_request,
            test_evaluation=test_evaluation, human_approval_request=human_approval_request,
            approval_manager=approval_manager, approval_request_id=approval_request_id,
            registration_request_id=registration_request_id,
            registration_plan=registration_plan, registration_result=registration_result,
            verification_result=verification_result, rollback_result=rollback_result,
        )
        return _build_capability_lifecycle_decision(lifecycle_state)

    def evaluate_code_change_correction_decision(self, code_change_result):
        """Take an already-produced `code_change_apply_and_test`
        capability result - the same input `evaluate_code_change_result`
        above accepts - and expose the small, structured "does this
        call for a correction" decision built on top of that same
        evaluation (Prompt 332: the code-change counterpart of
        `evaluate_correction_decision` above, which does the same for a
        bare `python_test_runner` result).

        Reuses `agent.code_change_evaluation.
        build_code_change_correction_decision` completely unchanged,
        which itself reuses `build_code_change_evaluation` completely
        unchanged - this method adds no classification or decision
        logic of its own, it only makes that existing, standalone
        decision reachable as part of this loop's own context, the
        same way `evaluate_code_change_result` above does for the plain
        evaluation. Needs no optional collaborator to have been
        supplied to `__init__`, exactly like `evaluate_code_change_
        result`.

        Always returns `{"correction_required": <bool>, "reason":
        <"PASSED"|"FAILED"|"TIMEOUT"|"CHANGE_FAILED"|"INVALID">,
        "source_test_status": <the underlying test status, or None>}`
        - see `build_code_change_correction_decision`'s own docstring
        for the exact, fixed rule: `correction_required` is `True` only
        when the final test status is FAILED or TIMEOUT; PASSED,
        INVALID, and a failed change (test never ran) are all `False`.

        A read-only decision step, not a new correction engine and not
        a duplicate evaluation/testing system: it never modifies a
        file, never runs or re-runs a test, never applies or re-applies
        a change, and never executes a capability, step, or Plan of its
        own - it only reports a structured decision for a caller to act
        on explicitly. `run()` itself never calls this automatically,
        same "explicitly invoked by a caller" convention
        `evaluate_code_change_result`/`evaluate_correction_decision`
        above already follow.

        Never raises: exactly like `evaluate_code_change_result`, a
        malformed `code_change_result` is reported as `"reason":
        "INVALID"`, `"correction_required": False`,
        `"source_test_status": None`, never an exception propagating
        out of this method."""
        return build_code_change_correction_decision(code_change_result)

    # ------------------------------------------------------------------
    # Generated code execution evaluation (Prompt 339: connect the
    # existing `execute_generated_code` result -
    # code_generation/generated_code_execution.py - to this loop's own
    # context via agent/generated_code_execution_evaluation.py's
    # `build_generated_code_execution_evaluation`, reused unchanged
    # rather than a second, differently-behaving classifier)
    # ------------------------------------------------------------------
    def evaluate_generated_code_execution_result(self, execution_result):
        """Classify an already-produced
        `code_generation.generated_code_execution.execute_generated_code`
        result into one small, structured evaluation this loop can act
        on, mapping that result's own `status` onto the same
        PASSED/FAILED/TIMEOUT/INVALID vocabulary every other evaluator
        on this loop already uses:

          - execution succeeded                    -> PASSED
          - execution returned an error             -> FAILED
          - execution exceeded the timeout          -> TIMEOUT
          - execution was rejected before running   -> INVALID

        Reuses `agent.generated_code_execution_evaluation.
        build_generated_code_execution_evaluation` completely
        unchanged - this method adds no classification logic of its
        own, it only makes that existing, standalone classifier
        reachable as part of this loop's own context, the same way
        `evaluate_test_result`/`evaluate_code_change_result` above do
        for their own respective results. Needs no optional
        collaborator to have been supplied to `__init__` -
        `build_generated_code_execution_evaluation` is a pure,
        stateless function, so this method is always available on
        every `AgentLoop`.

        Always returns
        `{"status", "target_file", "execution_status", "error",
        "correction_required"}` exactly as
        `build_generated_code_execution_evaluation` itself already
        shapes it - see that function's own docstring for the precise,
        fixed rules, including `correction_required` being `True` only
        for a final FAILED or TIMEOUT status, and the original
        `target_file`/`error` always being preserved, completely
        unmodified, from the execution result.

        Purely a read-only classification step: never re-executes the
        generated code, never modifies it, never re-applies or
        re-writes it, and never executes a capability, step, or Plan
        of its own. `run()` itself never calls this automatically, and
        this method never performs a correction or modifies the Plan
        on its own - same "explicitly invoked by a caller, no
        automatic follow-up action" convention
        `evaluate_test_result`/`evaluate_code_change_result` above
        already follow.

        Never raises: an input that isn't a real
        `execute_generated_code` result is reported as
        `"status": "INVALID"`, `"correction_required": False`, never
        an exception propagating out of this method."""
        return build_generated_code_execution_evaluation(execution_result)

    # ------------------------------------------------------------------
    # Code error analysis (Prompt 340: connect the existing
    # `execute_generated_code` result and its existing evaluation -
    # agent/generated_code_execution_evaluation.py - to this loop's own
    # context via agent/code_error_analysis.py's
    # `build_code_error_analysis`, reused unchanged rather than a
    # second, differently-behaving error-analysis or evaluation system)
    # ------------------------------------------------------------------
    def analyze_generated_code_error(self, execution_result):
        """Extract a small, structured `CodeErrorAnalysis` - `{
        target_file, error_type, error_message, stderr, line_number,
        is_actionable}` - from an already-produced
        `code_generation.generated_code_execution.execute_generated_code`
        result, using only what that result (and the existing
        evaluation already built on top of it) deterministically make
        available.

        Reuses `agent.code_error_analysis.build_code_error_analysis`
        completely unchanged - this method adds no extraction or
        classification logic of its own, it only makes that existing,
        standalone analysis step reachable as part of this loop's own
        context, the same way `evaluate_generated_code_execution_result`
        above does for the plain evaluation it itself is built on.
        Needs no optional collaborator to have been supplied to
        `__init__` - `build_code_error_analysis` is a pure, stateless
        function, so this method is always available on every
        `AgentLoop`.

        `error_type` is one of `SyntaxError`/`NameError`/`TypeError`/
        `ImportError`/`RuntimeError`/`TIMEOUT`/`UNKNOWN_ERROR`, or
        `None` when execution actually succeeded or was rejected
        before ever running - see `build_code_error_analysis`'s own
        docstring for the exact, fixed extraction rules, including
        `is_actionable` being derived from nothing but `error_type`
        via one fixed lookup table, and `line_number` only ever being
        populated when a real Python traceback frame is present in
        `stderr`.

        Purely a read-only extraction step: never modifies the
        generated source file or `execution_result`, never generates
        or applies a correction, and never executes or re-executes
        anything - it only reads the already-produced execution result
        (and its existing evaluation) and reports what,
        deterministically, went wrong. `run()` itself never calls this
        automatically, same "explicitly invoked by a caller, no
        automatic follow-up action" convention every other
        `evaluate_*`/`analyze_*` method on this loop already follows.

        Never raises: an input that isn't a real
        `execute_generated_code` result is reported the same safe way
        `evaluate_generated_code_execution_result` itself already
        guarantees - `error_type=None`, `is_actionable=False` - never
        an exception propagating out of this method."""
        return build_code_error_analysis(execution_result)

    # ------------------------------------------------------------------
    # Code correction proposal (Prompt 341: connect the existing
    # CodeErrorAnalysis - agent/code_error_analysis.py - to one small,
    # structured, inert correction proposal via
    # agent/code_correction_proposal.py's
    # `build_code_correction_proposal`, reused unchanged rather than a
    # second, differently-behaving correction system)
    # ------------------------------------------------------------------
    def propose_code_correction(self, execution_result):
        """Take an already-produced
        `code_generation.generated_code_execution.execute_generated_code`
        result - the same input `evaluate_generated_code_execution_result`/
        `analyze_generated_code_error` above accept - and, reusing the
        existing evaluation and error-analysis steps this loop already
        exposes, expose one small, structured, inert correction
        proposal built on top of them.

        Reuses, unchanged: `build_generated_code_execution_evaluation`
        (Prompt 339) and `build_code_error_analysis` (Prompt 340) are
        each called exactly once to (re)compute the evaluation and the
        `CodeErrorAnalysis` this proposal is based on - the same two
        pure, stateless classifiers `evaluate_generated_code_execution_
        result`/`analyze_generated_code_error` above already expose -
        and `agent.code_correction_proposal.
        build_code_correction_proposal` (Prompt 341) is then called,
        unchanged, on that `CodeErrorAnalysis` to build the proposal
        itself. This method adds no classification or proposal logic
        of its own - it only makes that existing, standalone step
        reachable as part of this loop's own context, and bundles it
        together with the results it was built from. Needs no optional
        collaborator to have been supplied to `__init__` - every
        function this method calls is pure and stateless, so it is
        always available on every `AgentLoop`.

        Also reuses, unchanged (Prompt 347): once `error_analysis` is
        computed, this loop's own `self.retrieve_successful_correction_
        patterns(error_analysis["error_type"])` (Prompt 346 - wired to
        `agent.code_correction_pattern_retrieval.
        retrieve_successful_correction_patterns` and this loop's own
        `self.learning_records`) is called exactly once to look up any
        previously-successful patterns for this same error_type, and
        the result is handed to `build_code_correction_proposal` as
        pure, optional, advisory `learned_patterns` context (never a
        second lookup or a second learning system - requirement 1).
        `retrieve_successful_correction_patterns` already returns `[]`
        on a miss (no store configured, unknown/blank error_type, or
        nothing recorded yet), so a proposal is generated exactly as
        before whenever no learned pattern exists (requirement 8).

        Always returns:
            {
                "execution_result": <the exact, unmodified
                    execution_result this method was called with -
                    requirement: "preserve the original ... execution
                    ... results">,
                "evaluation": <the exact dict
                    evaluate_generated_code_execution_result(
                    execution_result) itself would return - requirement:
                    "preserve the original ... evaluation ... results">,
                "error_analysis": <the exact dict
                    analyze_generated_code_error(execution_result)
                    itself would return - requirement: "preserve the
                    original ... error-analysis results">,
                "learned_patterns": <the exact list
                    self.retrieve_successful_correction_patterns(
                    error_analysis["error_type"]) itself would return
                    - requirement 9's "preserve ... learned patterns";
                    "[]" whenever nothing successful is on record for
                    this error_type>,
                "proposal": <the exact dict
                    build_code_correction_proposal(error_analysis,
                    learned_patterns=learned_patterns) itself would
                    return - {"target_file", "error_type", "reason",
                    "change_description", "status", "ready_to_apply",
                    "apply_capability", "learned_patterns"} - see that
                    function's own docstring for the precise, fixed
                    rules, including a proposal only ever being
                    generated when the evaluation/error-analysis
                    already found execution FAILED or TIMEOUT and
                    is_actionable is True, and "NOT_READY" (never a
                    guess) whenever an exact correction can't be
                    safely determined - a matching learned pattern
                    never overrides this independent check
                    (requirements 4, 5, 7)>,
            }

        Purely a connecting, read-only step: never modifies
        `execution_result`, the generated source file, or any other
        file, never applies the proposal it returns, and never
        executes or re-executes anything - `code_change_plan` (the
        existing capability this proposal's own `apply_capability`
        field names, when ready) is never called by this method
        either, since doing so would need a real source-code fragment
        this loop never invents (see `build_code_correction_proposal`'s
        own docstring). Looking up `learned_patterns` never applies,
        stores, or copies anything either (requirement 6) - it is a
        read-only lookup exactly like every other call to
        `self.retrieve_successful_correction_patterns` already is.
        `run()` itself never calls this automatically, same
        "explicitly invoked by a caller, no automatic follow-up
        action" convention every other `evaluate_*`/`analyze_*`
        method on this loop already follows.

        Never raises: exactly like `evaluate_generated_code_execution_
        result`/`analyze_generated_code_error`, an input that isn't a
        real `execute_generated_code` result still yields a fully
        structured result - `proposal["status"]` is `"NOT_READY"`
        with an explanatory `proposal["reason"]` and `learned_patterns`
        is `[]` (no usable `error_type` to look anything up by) -
        never an exception propagating out of this method."""
        evaluation = build_generated_code_execution_evaluation(execution_result)
        error_analysis = build_code_error_analysis(execution_result)
        learned_patterns = self.retrieve_successful_correction_patterns(
            error_analysis.get("error_type") if isinstance(error_analysis, dict) else None
        )
        proposal = build_code_correction_proposal(error_analysis, learned_patterns=learned_patterns)
        return {
            "execution_result": execution_result,
            "evaluation": evaluation,
            "error_analysis": error_analysis,
            "learned_patterns": learned_patterns,
            "proposal": proposal,
        }

    # ------------------------------------------------------------------
    # Code correction proposal validation (Prompt 342: connect the
    # existing code-correction proposal - agent/code_correction_
    # proposal.py - to this loop's own context via
    # agent/code_correction_proposal_validation.py's
    # `build_code_correction_proposal_validation`, reused unchanged
    # rather than a second, differently-behaving validation system)
    # ------------------------------------------------------------------
    def validate_code_correction_proposal(self, proposal, allowed_dirs=None):
        """Decide whether an already-built
        `agent.code_correction_proposal.build_code_correction_proposal`
        result - typically `propose_code_correction(...)["proposal"]`
        above - is safe to ever apply, using only what that proposal
        already claims plus one existing, reused path-safety check.

        Reuses `agent.code_correction_proposal_validation.
        build_code_correction_proposal_validation` completely
        unchanged - this method adds no validation logic of its own,
        it only makes that existing, standalone step reachable as
        part of this loop's own context, the same way every other
        `evaluate_*`/`analyze_*`/`propose_*` method on this loop does
        for the step it wraps. Needs no optional collaborator to have
        been supplied to `__init__` -
        `build_code_correction_proposal_validation` is a pure,
        stateless function, so this method is always available on
        every `AgentLoop`.

        `allowed_dirs`, if given, is forwarded unchanged to the
        underlying path-safety check - see that function's own
        docstring; omitted, the application's real default safe
        directories are used.

        Always returns `{"status", "target_file", "reason",
        "is_safe_to_apply"}` exactly as
        `build_code_correction_proposal_validation` itself already
        shapes it - see that function's own docstring for the precise,
        fixed rules, including `status` being `"VALID"` only when the
        proposal was itself `PROPOSED`, names a `target_file`, carries
        error information and a correction description, and that
        `target_file` is within the allowed directories -
        `"INVALID"`/`"NOT_READY"` (never a guess) otherwise, and
        `is_safe_to_apply` being `True` only for `"VALID"`.

        Purely a read-only validation step: never modifies `proposal`
        or `target_file`, never applies the proposal, and never
        executes or re-executes anything. `run()` itself never calls
        this automatically, same "explicitly invoked by a caller, no
        automatic follow-up action" convention every other
        `evaluate_*`/`analyze_*`/`propose_*` method on this loop
        already follows.

        Never raises: an input that isn't a real
        `CodeCorrectionProposal` is reported as `status="NOT_READY"`,
        `is_safe_to_apply=False`, never an exception propagating out
        of this method."""
        return build_code_correction_proposal_validation(proposal, allowed_dirs=allowed_dirs)

    # ------------------------------------------------------------------
    # Code correction application (Prompt 343: connect the existing
    # proposal-validation result - agent/code_correction_proposal_
    # validation.py - to the existing safe code-editing system
    # (execution/code_change_apply_capability.py, itself already built
    # on code_change_plan + text_file_edit) via agent/code_correction_
    # application.py's `build_code_correction_application`, reused
    # unchanged rather than a second, differently-behaving editing or
    # proposal system)
    # ------------------------------------------------------------------
    def apply_code_correction(self, proposal, validation_result, old_text, new_text, allowed_dirs=None):
        """Apply, at most, the one validated correction
        `validation_result` (typically
        `validate_code_correction_proposal(proposal)` above) describes,
        using only the existing `code_change_apply` capability - never
        a second edit system - and bundle the result together with the
        original `proposal`/`validation_result` this loop already
        computed.

        Reuses `agent.code_correction_application.
        build_code_correction_application` completely unchanged - this
        method adds no gating, fragment-matching, or file-writing
        logic of its own, it only makes that existing, standalone step
        reachable as part of this loop's own context, the same way
        every other `evaluate_*`/`analyze_*`/`propose_*`/`validate_*`
        method on this loop does for the step it wraps. Needs no
        optional collaborator to have been supplied to `__init__` -
        `build_code_correction_application` is a pure function calling
        only existing, stateless capability handlers, so this method
        is always available on every `AgentLoop`.

        `old_text`/`new_text` are the concrete source fragment and its
        replacement - a caller must supply these explicitly, since
        neither `CodeErrorAnalysis` (Prompt 340) nor
        `CodeCorrectionProposal` (Prompt 341) ever invents one (see
        each of their own docstrings); `target_file` is never taken
        from a separate parameter here, only from
        `validation_result["target_file"]`, so this method can never
        be pointed at a different file than the one that was actually
        validated (requirement 7).

        Always returns:
            {
                "proposal": <the exact, unmodified proposal this
                    method was called with - requirement: "preserve
                    the original proposal">,
                "validation_result": <the exact, unmodified
                    validation_result this method was called with -
                    requirement: "preserve the original ... validation
                    result">,
                "application": <the exact dict
                    build_code_correction_application(validation_result,
                    old_text, new_text, allowed_dirs=allowed_dirs)
                    itself would return - {"status", "target_file",
                    "changed", "error"} - see that function's own
                    docstring for the precise, fixed rules, including
                    a change only ever being applied when
                    validation_result is VALID and is_safe_to_apply,
                    and "NOT_READY" (never a guess, and never a
                    modified file) whenever the exact source fragment
                    can't be uniquely identified>,
            }

        Applies, at most, one controlled change per call, and never
        automatically applies a second one - `run()` itself never
        calls this automatically, same "explicitly invoked by a
        caller, no automatic follow-up action" convention every other
        `evaluate_*`/`analyze_*`/`propose_*`/`validate_*` method on
        this loop already follows. Never executes the modified file -
        this method (and everything it calls) only ever performs the
        one text write `text_file_edit`'s own handler already
        performs, exactly as `code_change_apply` documents; running
        the corrected file is a separate, later, explicitly-invoked
        step (`execute_generated_code`).

        Never raises: exactly like `build_code_correction_application`
        itself, an unsafe or otherwise-failing precondition is
        reported as `application["status"]="ERROR"` with an
        explanatory `application["error"]`, never an exception
        propagating out of this method."""
        application = build_code_correction_application(
            validation_result, old_text, new_text, allowed_dirs=allowed_dirs,
        )
        return {
            "proposal": proposal,
            "validation_result": validation_result,
            "application": application,
        }

    # ------------------------------------------------------------------
    # Code change -> Self-Upgrade adapter (Prompt 349: connect the
    # existing, already-validated code-correction result above
    # (apply_code_correction, Prompt 343) to the existing Self-Upgrade
    # pipeline - self_upgrade/upgrade_system.py's UpgradeSystem,
    # unchanged - via agent/code_change_self_upgrade_adapter.py's
    # `build_self_upgrade_input_from_code_correction`, reused unchanged
    # rather than a second correction or Self-Upgrade system)
    # ------------------------------------------------------------------
    def build_self_upgrade_input(self, correction_result):
        """Convert an already-validated, already-applied code
        correction (typically `apply_code_correction(...)` above,
        Prompt 343) into the small input the existing Self-Upgrade
        pipeline's `UpgradeSystem.propose_upgrade(name, description,
        payload=None)` already accepts - never a second correction or
        Self-Upgrade system.

        Reuses `agent.code_change_self_upgrade_adapter.
        build_self_upgrade_input_from_code_correction` completely
        unchanged - this method adds no gating logic of its own, it
        only makes that existing, standalone adapter reachable as part
        of this loop's own context, the same way `apply_code_correction`
        above does for `build_code_correction_application`.

        Always returns:
            {
                "status": <"ACCEPTED" or "REJECTED">,
                "reason": <str explaining the verdict>,
                "self_upgrade_input": <None for REJECTED; for
                    ACCEPTED, {"name", "description", "payload"} -
                    ready to pass as
                    `upgrade_system.propose_upgrade(**self_upgrade_input)`>,
            }

        Only a validated *and* successfully applied change is ever
        converted - an invalid, not-ready, rejected, or errored
        proposal/change is always reported as REJECTED, and never
        reaches the Self-Upgrade pipeline.

        Never installs or activates an upgrade itself - this method
        never calls `UpgradeSystem.propose_upgrade` (or any other
        Self-Upgrade method); it only ever builds the input a caller
        may later, separately, explicitly hand to that existing
        pipeline. Never executes anything, and never raises: see
        `build_self_upgrade_input_from_code_correction`'s own
        docstring for the exact, fixed rules."""
        return build_self_upgrade_input_from_code_correction(correction_result)

    # ------------------------------------------------------------------
    # Code change -> Self-Upgrade readiness (Prompt 350: connect the
    # existing CODE_CHANGE adapter above (Prompt 349) to the existing
    # Self-Upgrade validation/sandbox stage - self_upgrade/sandbox.py's
    # Sandbox, unchanged - via agent/code_change_self_upgrade_
    # validation.py's `build_code_change_self_upgrade_readiness`,
    # reused unchanged rather than a second adapter, sandbox, or
    # validation system)
    # ------------------------------------------------------------------
    def evaluate_self_upgrade_readiness(
        self, correction_result, original_fragment, replacement, test_status, sandbox=None,
    ):
        """Decide whether an already-validated, already-applied,
        already-retested code change (typically
        `apply_code_correction(...)` above, Prompt 343, plus the
        `original_fragment`/`replacement` fragment supplied to it and
        a `test_status` from `retest_code_correction(...)` above,
        Prompt 344) is READY to be handed to the existing Self-Upgrade
        pipeline, or must be REJECTED - never a second correction,
        adapter, or Self-Upgrade system.

        Reuses `agent.code_change_self_upgrade_validation.
        build_code_change_self_upgrade_readiness` completely unchanged
        - this method adds no gating logic of its own, it only makes
        that existing, standalone readiness check reachable as part of
        this loop's own context, the same way `build_self_upgrade_input`
        above does for `build_self_upgrade_input_from_code_correction`.

        Always returns:
            {
                "status": <"READY" or "REJECTED">,
                "reason": <str explaining the verdict>,
                "target_file": <the target file this check was for, or
                    None when it could not be determined>,
            }

        Never installs, activates, versions, or permanently modifies
        anything itself - this method never calls `UpgradeSystem.
        propose_upgrade` or any `VersionSystem` method; it only ever
        reports whether the change is ready for that existing,
        separate, explicitly-invoked pipeline. Never executes
        anything, and never raises: see
        `build_code_change_self_upgrade_readiness`'s own docstring for
        the exact, fixed rules."""
        return build_code_change_self_upgrade_readiness(
            correction_result, original_fragment, replacement, test_status, sandbox=sandbox,
        )

    # ------------------------------------------------------------------
    # Code change Self-Upgrade change audit (Prompt 351: record a small,
    # structured audit entry for a CODE_CHANGE Self-Upgrade readiness
    # check above, via agent/code_change_self_upgrade_audit.py's
    # `CodeChangeAuditLog`/`build_code_change_audit_record`, reused
    # unchanged rather than a second logging or version system)
    # ------------------------------------------------------------------
    def record_self_upgrade_audit(
        self, correction_result, original_fragment, replacement, test_status, sandbox=None,
    ):
        """Run the existing readiness check above
        (`evaluate_self_upgrade_readiness`, Prompt 350, unchanged) and
        record a small, structured audit entry for the result into
        `self.audit_log` - an entry is recorded whether the readiness
        check is `READY` or `REJECTED` (requirement: audit both
        successful and rejected changes).

        Always returns:
            {
                "readiness": <the {status, reason, target_file} dict
                    `evaluate_self_upgrade_readiness` already returns>,
                "audit_record": <the {target_file, original_fragment,
                    replacement, validation_status, test_status,
                    result_status} dict that was recorded>,
            }

        Never installs, activates, versions, or permanently modifies
        anything beyond appending to `self.audit_log` - this method
        never calls `UpgradeSystem.propose_upgrade` or any
        `VersionSystem` method. Never raises: see
        `build_code_change_self_upgrade_readiness`'s and
        `build_code_change_audit_record`'s own docstrings for the
        exact, fixed rules each already follows."""
        readiness_result = self.evaluate_self_upgrade_readiness(
            correction_result, original_fragment, replacement, test_status, sandbox=sandbox,
        )
        audit_record = self.audit_log.record(
            correction_result, original_fragment, replacement, test_status, readiness_result,
        )
        return {"readiness": readiness_result, "audit_record": audit_record}

    def latest_self_upgrade_audit(self):
        """The most recently recorded CODE_CHANGE Self-Upgrade audit
        record (requirement: "a simple way to retrieve the latest
        audit record"), or `None` if none has been recorded yet.
        Never raises - reuses `CodeChangeAuditLog.latest` unchanged."""
        return self.audit_log.latest()

    # ------------------------------------------------------------------
    # Code change Self-Upgrade version snapshot (Prompt 352: connect an
    # already-READY CODE_CHANGE readiness check above to the existing
    # Self-Upgrade Version System - self_upgrade/version_system.py's
    # VersionSystem, unchanged - via agent/code_change_version_
    # snapshot.py's `build_code_change_version_snapshot`, reused
    # unchanged rather than a second version-management system)
    # ------------------------------------------------------------------
    def snapshot_self_upgrade_version(
        self, correction_result, test_status, readiness_result, audit_record=None, versions=None,
    ):
        """Create a version snapshot, via the existing, reused
        `VersionSystem.create_version` (self_upgrade/version_system.py,
        unchanged), for an already-READY CODE_CHANGE Self-Upgrade
        readiness check (typically `evaluate_self_upgrade_readiness(...)`
        above, Prompt 350) - or report `SKIPPED` when that check is not
        `READY` (requirement: "if validation or testing fails, do not
        create a successful version snapshot").

        Reuses `agent.code_change_version_snapshot.build_code_change_
        version_snapshot` completely unchanged - this method adds no
        gating logic of its own, it only makes that existing,
        standalone snapshot step reachable as part of this loop's own
        context, the same way `evaluate_self_upgrade_readiness` above
        does for `build_code_change_self_upgrade_readiness`.

        `versions`, if given, must be a `VersionSystem` instance (or a
        compatible `create_version`-providing object) - reused exactly
        as provided. Omitted, this loop's own `self.versions` (set only
        when a `version_system=` was supplied to `AgentLoop.__init__`)
        is used instead; if neither is available, the snapshot is
        `SKIPPED` rather than raising or silently building a new
        version system of this loop's own (requirement 6: "do not
        create a new version-management system").

        Always returns:
            {
                "status": <"CREATED" or "SKIPPED">,
                "reason": <str explaining the verdict>,
                "target_file": <the target file this snapshot is for,
                    or None when it could not be determined>,
                "version": <the version row VersionSystem.create_version
                    returned, for "CREATED"; None for "SKIPPED">,
            }

        Never installs or activates the change itself, and never
        touches `UpgradeSystem.propose_upgrade` or any of its own
        install-stage bookkeeping - this call only ever reaches
        `VersionSystem.create_version`, exactly once, and only for an
        already-READY change. Never raises: see
        `build_code_change_version_snapshot`'s own docstring for the
        exact, fixed rules it already follows."""
        active_versions = versions if versions is not None else getattr(self, "versions", None)
        return build_code_change_version_snapshot(
            correction_result, test_status, readiness_result, audit_record, active_versions,
        )

    # ------------------------------------------------------------------
    # Code change rollback (Prompt 353: connect an already-applied,
    # already-tested CODE_CHANGE to the existing rollback mechanism -
    # self_upgrade/version_system.py's VersionSystem.rollback_to,
    # unchanged - via agent/code_change_rollback.py's
    # `build_code_change_rollback_decision`, reused unchanged rather
    # than a second rollback or version system)
    # ------------------------------------------------------------------
    def decide_code_change_rollback(self, test_status, target_file, version, versions=None):
        """Decide whether an already-applied, already-tested
        CODE_CHANGE must be rolled back, and - only when it must -
        perform that rollback via the existing, reused
        `VersionSystem.rollback_to` (self_upgrade/version_system.py,
        unchanged).

        Reuses `agent.code_change_rollback.build_code_change_rollback_
        decision` completely unchanged - this method adds no gating
        logic of its own, it only makes that existing, standalone
        rollback step reachable as part of this loop's own context,
        the same way `snapshot_self_upgrade_version` above does for
        `build_code_change_version_snapshot`.

        `version` must be the version row already created for this
        exact change (typically `snapshot_self_upgrade_version(...)
        ["version"]` above, Prompt 352).

        `versions`, if given, must be a `VersionSystem` instance (or a
        compatible `rollback_to`-providing object) - reused exactly as
        provided. Omitted, this loop's own `self.versions` (set only
        when a `version_system=` was supplied to `AgentLoop.__init__`)
        is used instead; if neither is available on a change that
        needs a rollback, the result reports `ROLLBACK_FAILED` rather
        than raising or fabricating a version system of its own
        (requirement 7: "do not create a second rollback/version
        system").

        Always returns:
            {
                "change_status": <"KEPT", "ROLLED_BACK", or
                    "ROLLBACK_FAILED">,
                "test_status": <the value supplied, as-is>,
                "rollback_required": <True for FAILED/TIMEOUT, else
                    False>,
                "rollback_status": <"NOT_REQUIRED", "SUCCEEDED", or
                    "FAILED">,
                "target_file": <the value supplied, as-is>,
            }

        Never retries the change itself, and never touches
        `UpgradeSystem` or `VersionSystem.create_version` - this call
        only ever reaches `VersionSystem.rollback_to`, and only when a
        rollback is actually required. Never raises: see
        `build_code_change_rollback_decision`'s own docstring for the
        exact, fixed rules it already follows."""
        active_versions = versions if versions is not None else getattr(self, "versions", None)
        return build_code_change_rollback_decision(
            test_status, target_file, version, active_versions,
        )

    # ------------------------------------------------------------------
    # Code change upgrade result (Prompt 354: a small, structured result
    # that summarizes the complete CODE_CHANGE self-upgrade flow above -
    # via agent/code_change_upgrade_result.py's
    # `build_code_change_upgrade_result`, reused unchanged rather than a
    # second CODE_CHANGE, audit, validation, testing, version, or
    # rollback system)
    # ------------------------------------------------------------------
    def build_code_change_upgrade_result(
        self, correction_result, readiness_result, snapshot_result, rollback_result,
    ):
        """Summarize an already-finished CODE_CHANGE self-upgrade flow -
        typically `evaluate_self_upgrade_readiness(...)` (Prompt 350),
        `snapshot_self_upgrade_version(...)` (Prompt 352), and
        `decide_code_change_rollback(...)` (Prompt 353) above, each
        already run once for this exact change, in that order - into
        one small, structured, serializable result.

        Reuses `agent.code_change_upgrade_result.
        build_code_change_upgrade_result` completely unchanged - this
        method adds no gating logic of its own, it only makes that
        existing, standalone summary step reachable as part of this
        loop's own context, the same way `decide_code_change_rollback`
        above does for `build_code_change_rollback_decision`.

        Always returns:
            {
                "target_file": <str or None>,
                "validation_status": <correction_result
                    ["validation_result"]["status"], or None>,
                "change_status": <"KEPT"/"ROLLED_BACK"/
                    "ROLLBACK_FAILED", or None>,
                "test_status": <the relevant test's already-classified
                    outcome, or None>,
                "version_status": <"CREATED"/"SKIPPED", or None>,
                "rollback_required": <bool, or None>,
                "rollback_status": <"NOT_REQUIRED"/"SUCCEEDED"/
                    "FAILED", or None>,
                "final_status": <"SUCCESS"/"FAILED"/"ROLLED_BACK"/
                    "REJECTED">,
            }

        Never retries the change and never starts another upgrade -
        this method contains no call to any correction, validation,
        sandbox, version, or rollback method; it only reads the three
        already-finished results it is handed. Never raises: see
        `build_code_change_upgrade_result`'s own docstring for the
        exact, fixed rules it already follows.

        Requirement 3 (Prompt 356): receiving this result also
        deterministically advances this loop's own controlled upgrade
        state (`self._upgrade_state`, reachable via
        `get_upgrade_state()` below) via the existing, unchanged
        `next_upgrade_state_from_result` - `COMPLETED`/`FAILED`/
        `ROLLED_BACK`/`REJECTED` for the matching `final_status`. This
        is purely a state *update*: it never starts a new upgrade and
        never retries this one (requirements 6, 7)."""
        result = build_code_change_upgrade_result(
            correction_result, readiness_result, snapshot_result, rollback_result,
        )
        self._upgrade_state = next_upgrade_state_from_result(result, self._upgrade_state)
        return result

    # ------------------------------------------------------------------
    # Code change upgrade state (Prompt 356: a small, deterministic
    # IDLE/IN_PROGRESS/COMPLETED/FAILED/ROLLED_BACK/REJECTED state model
    # tracking one CODE_CHANGE upgrade at a time on top of the Unified
    # Code Upgrade Result above - via agent/code_change_upgrade_state.py's
    # `can_start_upgrade`/`next_upgrade_state_from_result`, reused
    # unchanged rather than a second AgentLoop or state system)
    # ------------------------------------------------------------------
    def get_upgrade_state(self):
        """The current CODE_CHANGE upgrade state - one of
        `agent.code_change_upgrade_state.
        ALL_CODE_CHANGE_UPGRADE_STATES` (requirement 4). Reads
        `self._upgrade_state` as-is; never re-derives it. Never
        raises."""
        return self._upgrade_state

    def start_code_change_upgrade(self):
        """Requirement 5: begin tracking one new CODE_CHANGE upgrade,
        refusing to do so while another one is already `IN_PROGRESS` -
        via the existing, unchanged `can_start_upgrade` gate.

        This method only ever flips this loop's own upgrade state to
        `IN_PROGRESS`, or reports that it could not - it never calls
        any correction, validation, sandbox, version, rollback, or
        upgrade-result method itself (requirement 6: "do not
        automatically start another upgrade" - starting one is always
        this explicit, separate call, made by a caller, never
        triggered by this loop on its own).

        Always returns:
            {
                "started": <True if the state was IDLE or an already-
                    terminal state and was moved to IN_PROGRESS; False
                    if an upgrade was already IN_PROGRESS>,
                "state": <this loop's upgrade state after this call -
                    IN_PROGRESS for a successful start, otherwise the
                    unchanged, already-IN_PROGRESS state>,
                "reason": <str explaining the verdict>,
            }

        Never raises: reuses `can_start_upgrade`'s own "never raises"
        guarantee unchanged."""
        if not can_start_upgrade(self._upgrade_state):
            return {
                "started": False,
                "state": self._upgrade_state,
                "reason": (
                    "An upgrade is already IN_PROGRESS; a new upgrade "
                    "cannot start until it finishes."
                ),
            }
        self._upgrade_state = UPGRADE_STATE_IN_PROGRESS
        return {
            "started": True,
            "state": self._upgrade_state,
            "reason": "CODE_CHANGE upgrade started.",
        }

    # ------------------------------------------------------------------
    # Code correction retest (Prompt 344: connect the existing
    # correction-application result above (Prompt 343) to the existing
    # `python_test_runner` capability via agent/code_correction_retest.py's
    # `build_code_correction_retest`, reused unchanged rather than a
    # second, differently-behaving test runner or evaluator)
    # ------------------------------------------------------------------
    def retest_code_correction(
        self, correction_result, original_test_result, test_path=None, target=None,
        allowed_dirs=None,
    ):
        """Run the existing `python_test_runner` system again against
        the file an already-applied correction
        (`apply_code_correction(...)` above, Prompt 343) modified, and
        compare that retest to the original, already-produced failing
        result - only when the correction was actually applied and the
        original result was a real failure (see
        `agent.code_correction_retest`'s own module docstring for the
        exact gate).

        Reuses `agent.code_correction_retest.build_code_correction_retest`
        completely unchanged - this method adds no gating, test-running,
        or comparison logic of its own, it only makes that existing,
        standalone step reachable as part of this loop's own context,
        the same way `apply_code_correction` above does for
        `build_code_correction_application`. Needs no optional
        collaborator to have been supplied to `__init__`.

        Always returns `{"correction_result", "original_evaluation",
        "retest_performed", "retest_evaluation", "comparison"}` exactly
        as `build_code_correction_retest` itself already shapes it -
        see that function's own docstring for the precise, fixed rules,
        including a retest only ever running when the correction's own
        `application["status"]` is `APPLIED` and the original result
        classifies as `FAILED`/`TIMEOUT` (a `PASSED` original never
        enters this path), and the original result/retest result/
        comparison always being preserved as three separate fields.

        Runs, at most, one retest per call, and never automatically
        applies another correction or retries the retest itself - same
        "explicitly invoked by a caller, no automatic follow-up action"
        convention `apply_code_correction` above already follows.

        Never raises: exactly like `build_code_correction_retest`
        itself, a retest that cannot even start is reported via
        `retest_evaluation`'s own `INVALID` classification, never an
        exception propagating out of this method."""
        return build_code_correction_retest(
            correction_result, original_test_result, test_path=test_path,
            target=target, allowed_dirs=allowed_dirs,
        )

    # ------------------------------------------------------------------
    # Code correction learning (Prompt 345: connect the existing
    # retest/comparison result above (Prompt 344) to the existing
    # Learning system - learning/learning_record.py,
    # learning/learning_record_store.py - via agent/
    # code_correction_learning.py's `build_code_correction_learning_
    # record`, reused unchanged rather than a second, differently-
    # behaving learning system)
    # ------------------------------------------------------------------
    def learn_from_code_correction(self, retest_result):
        """Build one `LearningRecord` describing an already-produced
        `retest_result` (`retest_code_correction(...)` above, Prompt
        344) and, if this `AgentLoop` was constructed with a
        `learning_record_store` (see `__init__`/`self.learning_
        records`), store it there - the exact same existing store
        `_relevant_learning_records` above already reads from.

        Reuses `agent.code_correction_learning.
        build_code_correction_learning_record` completely unchanged -
        this method adds no classification or record-shaping logic of
        its own, it only makes that existing, standalone step
        reachable as part of this loop's own context, the same way
        `apply_code_correction`/`retest_code_correction` above do for
        the steps they wrap.

        Always returns the built `LearningRecord`'s own `to_dict()`
        alongside whether it was actually stored:
            {
                "record": <the exact dict
                    build_code_correction_learning_record(retest_result)
                    .to_dict() itself would return>,
                "stored": <bool - True only when this AgentLoop has a
                    learning_record_store and that store's own `add`
                    accepted the record>,
            }

        `self.learning_records` being `None` (no store configured) is
        handled exactly like `_relevant_learning_records` already
        handles it - `"stored": False`, never raised.

        A correction is recorded as successful knowledge only when the
        retest itself is PASSED - a rejected, not-ready, or still-
        failing correction is still recorded (never silently dropped),
        just never as `outcome=OUTCOME_SUCCESS` - see
        `agent.code_correction_learning`'s own module docstring for the
        exact, fixed rule (requirements 3, 4).

        Never applies another correction, never retries the retest,
        and never modifies `retest_result` itself (requirements 7, 8,
        9) - same "explicitly invoked by a caller, no automatic
        follow-up action" convention `apply_code_correction`/
        `retest_code_correction` above already follow. `run()` itself
        never calls this automatically.

        Never raises: exactly like `build_code_correction_learning_
        record`, any input shape is handled safely - a malformed
        `retest_result` simply yields a record whose fields are
        `None`/`False` rather than an exception propagating out of
        this method."""
        record = build_code_correction_learning_record(retest_result)
        stored = False
        if self.learning_records is not None:
            stored = self.learning_records.add(record) is not None
        return {"record": record.to_dict(), "stored": stored}

    # ------------------------------------------------------------------
    # Code correction pattern retrieval (Prompt 346: let this loop look
    # up previously-recorded, successful code-correction learning
    # records above (Prompt 345) for a given error_type, before ever
    # generating a new correction proposal, via agent/code_correction_
    # pattern_retrieval.py's `retrieve_successful_correction_patterns`,
    # reused unchanged rather than a second learning database or
    # pattern system)
    # ------------------------------------------------------------------
    def retrieve_successful_correction_patterns(self, error_type):
        """Every previously-recorded, successful code-correction
        learning record (Prompt 345 - `learn_from_code_correction`
        above) relevant to `error_type`, read from this loop's own
        `self.learning_records` (the exact same store `_relevant_
        learning_records`/`learn_from_code_correction` above already
        read from and write into - never a second store).

        Reuses `agent.code_correction_pattern_retrieval.
        retrieve_successful_correction_patterns` completely unchanged -
        this method adds no filtering, scoring, or lookup logic of its
        own, it only makes that existing, standalone step reachable as
        part of this loop's own context and supplies it with this
        loop's own configured store, the same way `_relevant_learning_
        records` above already does for its own, differently-scoped
        lookup.

        Always returns a plain list (never `None`) of `to_dict()`-
        shaped records - `[]` when this `AgentLoop` has no configured
        `learning_record_store` at all, when `error_type` isn't a
        usable non-empty string, or when nothing successful has been
        recorded yet for it (requirement 7) - the exact same "safe on
        a miss" convention `_relevant_learning_records` already
        follows.

        Purely a read-only retrieval step: never builds or stores a
        learning record, never applies a correction, never modifies a
        source file, and never runs or re-runs a test (requirements 9,
        10, 11). `run()` itself never calls this automatically, and
        calling it changes nothing about this loop's existing behavior
        - same "explicitly invoked by a caller, no automatic follow-up
        action" convention every other `evaluate_*`/`apply_*`/
        `retrieve_*` method on this loop already follows (requirement
        12: "preserve all existing behavior").

        Never raises: exactly like `retrieve_successful_correction_
        patterns` itself, an unusable `error_type` or a missing store
        is reported as `[]`, never an exception propagating out of
        this method."""
        records = retrieve_successful_correction_patterns(self.learning_records, error_type)
        return [record.to_dict() for record in records]

    def request_code_change_correction_analysis(self, goal_id, plan_id, code_change_result):
        """Connect the code-change correction decision above (Prompt
        332: `evaluate_code_change_correction_decision`, built on
        `code_change_evaluation.build_code_change_correction_decision`)
        to this loop's existing `AdaptivePlanAnalyzer` (see
        `request_analysis`): when - and only when - `code_change_result`
        classifies as requiring a correction, analyze the current Plan
        for the already-recorded blockers/incomplete steps that might
        explain why, using the exact same read-only
        `AdaptivePlanAnalyzer.analyze` this loop already exposes via
        `request_analysis`/`request_correction_analysis` - never a
        second, differently-behaving analyzer (requirements 1, 2, 8).

        This is the `code_change_apply_and_test`-result counterpart of
        `request_correction_analysis` above, which does the same for a
        bare `python_test_runner` result; the two are deliberately
        parallel, and neither replaces the other.

        Always returns:
            {
                "change_result": <code_change_result["change_result"]
                    unchanged, or None if code_change_result isn't a
                    dict - requirement 7: "preserve ... original
                    change result">,
                "test_result": <code_change_result["test_result"]
                    unchanged, or None if code_change_result isn't a
                    dict - requirement 7: "preserve ... test result">,
                "correction": <the exact dict
                    evaluate_code_change_correction_decision(
                    code_change_result) itself would return -
                    requirement 7: "preserve ... correction
                    decision">,
                "analysis_performed": <bool>,
                "analysis": <the exact dict request_analysis(goal_id,
                    plan_id) itself would return, if
                    "analysis_performed" is True; otherwise None -
                    requirement 7: "preserve ... plan analysis
                    result">,
            }

        `"analysis_performed"`/`"analysis"` are derived from nothing
        but `correction["correction_required"]`
        (`evaluate_code_change_correction_decision`'s own, already-
        deterministic decision) - never re-classifies
        `code_change_result` a second way (requirements 3, 4):
          - `correction_required` is `False` (a PASSED test, an
            INVALID result, or a failed change that never even ran a
            test) -> `analysis_performed=False`, `analysis=None`. No
            Plan analysis is performed at all.
          - `correction_required` is `True` (the final test status is
            FAILED or TIMEOUT) -> calls `self.request_analysis(
            goal_id, plan_id)` unchanged and returns its result
            verbatim under `"analysis"`.

        Only `goal_id`/`plan_id` are passed to the analyzer - the same
        existing identifiers `request_analysis`/
        `request_correction_analysis` already take (requirement 5:
        "the analysis request must include only the relevant
        execution/test result needed by the existing analyzer" -
        `AdaptivePlanAnalyzer.analyze` needs nothing from
        `code_change_result` itself, since it already has its own,
        complete source of truth in the Goal/Plan/step records
        `GoalManager`/`PlanManager`/`GoalCompletionEvaluator` already
        keep). Nothing derived from `code_change_result` is passed
        into the analyzer, and nothing here fabricates a blocker of
        its own.

        Purely a connecting step, not a new analyzer and not a new
        planning system (requirements 6, 8, 9, 10): never modifies the
        Goal, the Plan, or any PlanStep - both
        `evaluate_code_change_correction_decision`/`request_analysis`
        it calls into are already fully read-only - never executes a
        capability, step, or Plan of its own, never generates or
        applies a correction proposal, and never automatically
        retries or triggers another step. `run()` itself never calls
        this automatically, same "explicitly invoked by a caller"
        convention every other `request_*`/`evaluate_*` method on
        this loop already follows.

        Missing or unknown Plan data is handled exactly as safely as
        `request_analysis`/`request_correction_analysis` already
        handle it on their own: an unknown `goal_id`, an unknown
        `plan_id`, or a `plan_id` that doesn't belong to `goal_id`
        never raises here - `AdaptivePlanAnalyzer.analyze` itself
        already reports that as `analysis_status="UNKNOWN"` with an
        explanatory warning, returned unchanged under `"analysis"`.

        Raises `ValueError` - via `request_analysis` - only if this
        `AgentLoop` was never supplied an `analyzer`, and only when
        `correction_required` is actually `True` (so a correction
        that doesn't require analysis never needs one to be
        supplied)."""
        decision = build_code_change_correction_decision(code_change_result)
        is_dict = isinstance(code_change_result, dict)
        change_result = code_change_result.get("change_result") if is_dict else None
        test_result = code_change_result.get("test_result") if is_dict else None

        if not decision["correction_required"]:
            return {
                "change_result": change_result,
                "test_result": test_result,
                "correction": decision,
                "analysis_performed": False,
                "analysis": None,
            }
        analysis = self.request_analysis(goal_id, plan_id)
        return {
            "change_result": change_result,
            "test_result": test_result,
            "correction": decision,
            "analysis_performed": True,
            "analysis": analysis,
        }

    def request_code_change_correction_proposal(self, goal_id, plan_id, code_change_result):
        """Connect `request_code_change_correction_analysis` above
        (Prompt 333) to this loop's existing `AdaptivePlanProposal`
        (see `request_proposal`): when - and only when - the code-
        change correction analysis actually identifies blockers or
        other incomplete work, generate the same structured, read-
        only correction proposal `request_proposal`/
        `request_correction_proposal` already expose, using the exact
        same `AdaptivePlanProposal.propose` this loop already reuses -
        never a second, differently-behaving proposal system
        (requirements 1, 2, 10).

        This is the `code_change_apply_and_test`-result counterpart of
        `request_correction_proposal` below, which does the same for a
        bare `python_test_runner` result; the two are deliberately
        parallel, and neither replaces the other.

        Always returns:
            {
                "correction_analysis": <the exact dict
                    request_code_change_correction_analysis(goal_id,
                    plan_id, code_change_result) itself would return -
                    "change_result"/"test_result"/"correction"/
                    "analysis_performed"/"analysis" preserved
                    completely unmodified (requirement 5)>,
                "proposal_performed": <bool>,
                "proposal": <the exact dict request_proposal(goal_id,
                    plan_id) itself would return, if
                    "proposal_performed" is True; otherwise None>,
            }

        `"proposal_performed"`/`"proposal"` are derived from nothing
        but the nested `correction_analysis["analysis"]` -
        `AdaptivePlanAnalyzer.analyze`'s own, already-computed
        `analysis_status` (this method never re-inspects
        `code_change_result` a second time, and never re-derives or
        invents a blocker of its own) - requirements 3, 4:
          - no analysis was performed at all (`correction_required`
            was `False` - a PASSED test, an INVALID result, or a
            failed change that never even ran a test - so
            `correction_analysis["analysis"]` is `None`) ->
            `proposal_performed=False`, `proposal=None`. Nothing to
            propose a fix for.
          - the analysis itself is `"UNKNOWN"` (an unknown/mismatched
            `goal_id`/`plan_id`) -> `proposal_performed=False`,
            `proposal=None`. `"UNKNOWN"` means there is nothing on
            record to reason from, not a blocker or incomplete step.
          - the analysis is `"COMPLETE"` (every step already
            satisfies the Goal, and the analyzer found no blocker
            anyway) -> `proposal_performed=False`, `proposal=None`. A
            complete Plan has nothing to correct.
          - the analysis is `"INCOMPLETE"`, `"BLOCKED"`, or `"FAILED"`
            - i.e. it identified at least one blocker or some other
            still-incomplete work -> calls `self.request_proposal(
            goal_id, plan_id)` unchanged and returns its result
            verbatim under `"proposal"` (requirement 3: "produce one
            structured correction proposal").

        Only `goal_id`/`plan_id` are passed to `request_proposal`,
        which itself passes only those same two existing identifiers
        into `AdaptivePlanProposal.propose` (requirement 11: "reuse
        the existing proposal types and validation fields") - exactly
        what that method already expects. Nothing from
        `code_change_result`, and nothing invented by this method, is
        passed into the proposal generator; `propose` derives its own
        `ProposedChange`s entirely from the blockers its own analyzer
        call already computes.

        Purely a connecting step, not a new proposal system
        (requirements 6, 7, 8, 9, 10): never modifies the Goal, the
        Plan, or any PlanStep - every method it calls into
        (`request_code_change_correction_analysis`/`request_analysis`/
        `request_proposal`/`AdaptivePlanProposal.propose`) is already
        fully read-only - and never applies the proposal it returns,
        never modifies a source file, and never runs or re-runs a
        test. Never executes a capability, step, or Plan of its own,
        and never automatically retries or triggers another step -
        `run()` itself never calls this automatically, same
        "explicitly invoked by a caller" convention every other
        `request_*`/`evaluate_*` method on this loop already follows.

        Missing or unknown Plan/Goal data is handled exactly as safely
        as `request_code_change_correction_analysis`/`request_analysis`
        already handle it on their own: never raises for an unknown
        `goal_id` or `plan_id` - reported as `analysis_status=
        "UNKNOWN"` inside `correction_analysis`, with
        `proposal_performed=False` here rather than an invented
        proposal.

        Raises `ValueError` only when a proposal actually needs to be
        generated (blockers or incomplete work were identified) and
        this `AgentLoop` was never supplied a `proposal_generator`
        (via `request_proposal`), or, before that, only when a
        correction analysis actually needs to run and no `analyzer`
        was supplied (via `request_code_change_correction_analysis`) -
        the same two existing, already-documented guards, never a new
        one."""
        correction_analysis = self.request_code_change_correction_analysis(
            goal_id, plan_id, code_change_result
        )
        analysis = correction_analysis["analysis"]
        proposal_needed = (
            analysis is not None
            and analysis["analysis_status"] not in (ANALYSIS_COMPLETE, ANALYSIS_UNKNOWN)
        )
        if not proposal_needed:
            return {
                "correction_analysis": correction_analysis,
                "proposal_performed": False,
                "proposal": None,
            }
        proposal = self.request_proposal(goal_id, plan_id)
        return {
            "correction_analysis": correction_analysis,
            "proposal_performed": True,
            "proposal": proposal,
        }

    def request_correction_analysis(self, goal_id, plan_id, test_result):
        """Connect the correction decision above to this loop's
        existing `AdaptivePlanAnalyzer` (see `request_analysis`): when
        - and only when - `test_result` classifies as requiring a
        correction, analyze the current Plan for the already-recorded
        blockers/incomplete steps that might explain why, using the
        exact same read-only `AdaptivePlanAnalyzer.analyze` this loop
        already exposes via `request_analysis` - never a second,
        differently-behaving analyzer.

        Always returns:
            {
                "correction": <the exact dict
                               evaluate_correction_decision(test_result)
                               itself would return>,
                "analysis_performed": <bool>,
                "analysis": <the exact dict request_analysis(goal_id,
                             plan_id) itself would return, if
                             "analysis_performed" is True; otherwise
                             None>,
            }

        `"analysis_performed"`/`"analysis"` are derived from nothing
        but `correction["correction_required"]`
        (`evaluate_correction_decision`'s own, already-deterministic
        decision) - never re-classifies `test_result` a second way:
          - `correction_required` is `False` (e.g. `"PASSED"`) ->
            `analysis_performed=False`, `analysis=None`. No Plan
            analysis is performed at all - a passing result has
            nothing to explain.
          - `correction_required` is `True` (`"FAILED"`/`"TIMEOUT"`/
            `"INVALID"`) -> calls `self.request_analysis(goal_id,
            plan_id)` unchanged and returns its result verbatim under
            `"analysis"`.

        Only `goal_id`/`plan_id` - the same existing identifiers every
        other method on this loop already takes - are passed to the
        analyzer; nothing derived from `test_result` itself is passed
        in or used to shape the analysis, since `AdaptivePlanAnalyzer.
        analyze` already has its own, complete, already-structured
        source of truth (the Goal/Plan/step/capability/execution
        records `GoalManager`/`PlanManager`/`GoalCompletionEvaluator`
        already keep) and needs nothing else. This method invents
        nothing: it neither fabricates a blocker of its own nor
        passes any unstructured/free-form data into the analyzer.

        Purely a connecting step, not a new analyzer and not a new
        planning system: never modifies the Goal, the Plan, or any
        PlanStep (both `evaluate_correction_decision`/
        `request_analysis` it calls into are already fully read-only),
        never executes a capability, step, or Plan of its own, and
        never automatically retries or triggers another step - `run()`
        itself never calls this automatically, same "explicitly
        invoked by a caller" convention every other `request_*`/
        `evaluate_*` method on this loop already follows.

        Missing or unknown Plan data is handled exactly as safely as
        `request_analysis` already handles it on its own: an unknown
        `goal_id`, an unknown `plan_id`, or a `plan_id` that doesn't
        belong to `goal_id` never raises here - `AdaptivePlanAnalyzer.
        analyze` itself already reports that as
        `analysis_status="UNKNOWN"` with an explanatory warning (see
        that method's own docstring), returned unchanged under
        `"analysis"`.

        Raises `ValueError` - via `request_analysis` - only if this
        `AgentLoop` was never supplied an `analyzer`, and only when
        `correction_required` is actually `True` (so a correction
        that doesn't require analysis never needs one to be
        supplied)."""
        decision = build_correction_decision(test_result)
        if not decision["correction_required"]:
            return {
                "correction": decision,
                "analysis_performed": False,
                "analysis": None,
            }
        analysis = self.request_analysis(goal_id, plan_id)
        return {
            "correction": decision,
            "analysis_performed": True,
            "analysis": analysis,
        }

    def request_correction_proposal(self, goal_id, plan_id, test_result):
        """Connect `request_correction_analysis` above to this loop's
        existing `AdaptivePlanProposal` (see `request_proposal`): when
        - and only when - the correction analysis actually identifies
        blockers or other incomplete work, generate the same
        structured, read-only correction proposal `request_proposal`
        already exposes, using the exact same `AdaptivePlanProposal.
        propose` this loop already reuses - never a second,
        differently-behaving proposal system.

        Always returns:
            {
                "correction_analysis": <the exact dict
                    request_correction_analysis(goal_id, plan_id,
                    test_result) itself would return>,
                "proposal_performed": <bool>,
                "proposal": <the exact dict request_proposal(goal_id,
                    plan_id) itself would return, if
                    "proposal_performed" is True; otherwise None>,
            }

        `"proposal_performed"`/`"proposal"` are derived from nothing
        but the nested `correction_analysis["analysis"]` -
        `AdaptivePlanAnalyzer.analyze`'s own, already-computed
        `analysis_status` (this method never re-inspects `test_result`
        a second time, and never re-derives or invents a blocker of
        its own):
          - no analysis was performed at all (a `PASSED` result, so
            `correction_analysis["analysis"]` is `None`) ->
            `proposal_performed=False`, `proposal=None`. Nothing to
            propose a fix for.
          - the analysis itself is `"UNKNOWN"` (an unknown/mismatched
            `goal_id`/`plan_id` - see `AdaptivePlanAnalyzer.analyze`'s
            own docstring) -> `proposal_performed=False`,
            `proposal=None`. `"UNKNOWN"` means there is nothing on
            record to reason from, not a blocker or incomplete step -
            generating a proposal from it would mean inventing a fix
            for a plan this project doesn't actually have evidence
            about, so this method deliberately does not attempt one.
          - the analysis is `"COMPLETE"` (every step already
            satisfies the Goal, and the analyzer found no blocker
            anyway - see `AdaptivePlanAnalyzer.analyze`'s own
            COMPLETE/blockers cross-check) -> `proposal_performed=
            False`, `proposal=None`. A complete Plan has nothing to
            correct.
          - the analysis is `"INCOMPLETE"`, `"BLOCKED"`, or `"FAILED"`
            - i.e. it identified at least one blocker or some other
            still-incomplete work (`AdaptivePlanAnalyzer.analyze`
            itself guarantees `analysis_status` only ever leaves
            `"COMPLETE"` when there is truly nothing left to explain)
            -> calls `self.request_proposal(goal_id, plan_id)`
            unchanged and returns its result verbatim under
            `"proposal"`.

        Only `goal_id`/`plan_id` are passed to `request_proposal`,
        which itself passes only those same two existing identifiers
        into `AdaptivePlanProposal.propose` - exactly what that method
        already expects. Nothing from `test_result`, and nothing
        invented by this method, is passed into the proposal
        generator; `propose` derives its own `ProposedChange`s
        entirely from the blockers its own analyzer call already
        computes, exactly as it already does for `request_proposal`.

        Purely a connecting step, not a new proposal system: never
        modifies the Goal, the Plan, or any PlanStep - every method it
        calls into (`request_correction_analysis`/`request_analysis`/
        `request_proposal`/`AdaptivePlanProposal.propose`) is already
        fully read-only, and never applies the proposal it returns.
        Never executes a capability, step, or Plan of its own, and
        never automatically retries or triggers another step - `run()`
        itself never calls this automatically, same "explicitly
        invoked by a caller" convention every other `request_*`/
        `evaluate_*` method on this loop already follows. Preserves
        every existing validation/safety rule unchanged:
        `AdaptivePlanProposal.propose`'s own structural checks and
        `validate_proposal` remain exactly as they already are, and
        `run()`'s own `max_iterations`/safety limits are untouched -
        this method never calls `run()` or `execute_plan`.

        Missing or unknown Plan/Goal data is handled exactly as safely
        as `request_correction_analysis`/`request_analysis` already
        handle it on their own: never raises for an unknown `goal_id`
        or `plan_id` - reported as `analysis_status="UNKNOWN"` inside
        `correction_analysis`, with `proposal_performed=False` here
        rather than an invented proposal.

        Raises `ValueError` only when a proposal actually needs to be
        generated (blockers or incomplete work were identified) and
        this `AgentLoop` was never supplied a `proposal_generator`
        (via `request_proposal`), or, before that, only when a
        correction analysis actually needs to run and no `analyzer`
        was supplied (via `request_correction_analysis`) - the same
        two existing, already-documented guards, never a new one."""
        correction_analysis = self.request_correction_analysis(goal_id, plan_id, test_result)
        analysis = correction_analysis["analysis"]
        proposal_needed = (
            analysis is not None
            and analysis["analysis_status"] not in (ANALYSIS_COMPLETE, ANALYSIS_UNKNOWN)
        )
        if not proposal_needed:
            return {
                "correction_analysis": correction_analysis,
                "proposal_performed": False,
                "proposal": None,
            }
        proposal = self.request_proposal(goal_id, plan_id)
        return {
            "correction_analysis": correction_analysis,
            "proposal_performed": True,
            "proposal": proposal,
        }

    def request_correction_validation(self, goal_id, plan_id, test_result):
        """Connect `request_correction_proposal` above to this loop's
        existing `AdaptivePlanProposal.validate_proposal` - the
        project's already-existing proposal-validation logic (its own
        shape/status/change_type/target_step/proposed_data/confidence
        checks - see that method's own docstring) - never a second,
        differently-behaving validator.

        Always returns:
            {
                "correction_proposal": <the exact dict
                    request_correction_proposal(goal_id, plan_id,
                    test_result) itself would return>,
                "validation_performed": <bool>,
                "validation": <the exact dict
                    self._proposal_generator.validate_proposal(proposal)
                    itself would return, if "validation_performed" is
                    True; otherwise None>,
                "ready_for_application": <bool - True only when a
                    proposal was both generated and found valid>,
            }

        `"validation_performed"`/`"validation"`/`"ready_for_application"`
        are derived from nothing but the nested
        `correction_proposal["proposal_performed"]`/`["proposal"]` -
        this method never re-derives whether a proposal was needed a
        second way, and never invents a validation outcome:
          - no proposal was generated at all (`proposal_performed`
            is `False` - a `PASSED` result, or an analysis that was
            `"COMPLETE"`/`"UNKNOWN"`) -> `validation_performed=False`,
            `validation=None`, `ready_for_application=False`. Nothing
            exists yet to validate or apply.
          - a proposal was generated (`proposal_performed=True`) ->
            calls `self._proposal_generator.validate_proposal(proposal)`
            unchanged and returns its result verbatim under
            `"validation"`; `ready_for_application` is then exactly
            `validation["valid"]` - `True` only when every one of
            `validate_proposal`'s own checks passed, `False` for any
            invalid proposal (an invalid proposal is never marked
            ready).

        This method itself decides nothing about *whether* a proposal
        is safe to apply beyond relaying `validate_proposal`'s own,
        already-existing verdict - `ready_for_application` is a plain
        relabeling of `validation["valid"]`, not a second, competing
        judgment.

        Purely a connecting step, not a new validation system and not
        an apply step: never modifies the Goal, the Plan, or any
        PlanStep - `validate_proposal` itself is already fully
        read-only (it only ever reads from `plan_manager` to confirm a
        `target_step_id` exists), and every method this one calls into
        (`request_correction_proposal`/`request_correction_analysis`/
        `request_analysis`/`request_proposal`) is already fully
        read-only too. Never executes a capability, step, or Plan of
        its own, and never automatically retries, applies the
        proposal, or triggers another step - even when
        `ready_for_application` is `True`, this method only reports
        that the proposal is ready, it does not act on it.
        `run()` itself never calls this automatically, same
        "explicitly invoked by a caller" convention every other
        `request_*`/`evaluate_*` method on this loop already follows.
        Preserves every existing validation/safety rule unchanged:
        `validate_proposal`'s own checks are reused exactly as they
        already exist, and `run()`'s own `max_iterations`/safety
        limits are untouched - this method never calls `run()` or
        `execute_plan`.

        Missing or unknown Plan/Goal data is handled exactly as safely
        as `request_correction_proposal` already handles it on its
        own: never raises for an unknown `goal_id`/`plan_id` -
        `proposal_performed` (and so `validation_performed`/
        `ready_for_application`) is simply `False` in that case,
        rather than an invented validation result.

        Raises `ValueError` only in the same, already-documented cases
        `request_correction_proposal` itself already raises for -
        never a new guard of its own."""
        correction_proposal = self.request_correction_proposal(goal_id, plan_id, test_result)
        if not correction_proposal["proposal_performed"]:
            return {
                "correction_proposal": correction_proposal,
                "validation_performed": False,
                "validation": None,
                "ready_for_application": False,
            }
        validation = self._proposal_generator.validate_proposal(correction_proposal["proposal"])
        return {
            "correction_proposal": correction_proposal,
            "validation_performed": True,
            "validation": validation,
            "ready_for_application": bool(validation["valid"]),
        }

    def apply_correction_proposal(self, goal_id, plan_id, test_result):
        """Connect `request_correction_validation` above to this
        loop's existing `ProposalApplier` (planning/proposal_applier.py)
        - the project's already-existing, already-inert proposal-
        application logic (its own per-change-type checks - see that
        class's own docstring) - never a second, differently-behaving
        applier.

        Always returns:
            {
                "correction_validation": <the exact dict
                    request_correction_validation(goal_id, plan_id,
                    test_result) itself would return>,
                "application_performed": <bool - True only when this
                    call actually invoked ProposalApplier.apply_change>,
                "application": <the exact structured dict
                    self._proposal_applier.apply_change(plan, change)
                    itself would return, if "application_performed" is
                    True; otherwise None>,
            }

        `"application_performed"`/`"application"` are derived from
        nothing but the nested
        `correction_validation["ready_for_application"]`/
        `["correction_proposal"]["proposal"]["proposed_changes"]` -
        this method never re-derives validity a second way, and never
        invents an application outcome:
          - `ready_for_application` is `False` (no proposal was
            generated at all, or one was generated but
            `validate_proposal` found it invalid) ->
            `application_performed=False`, `application=None`. An
            invalid proposal - or the absence of one - is never
            applied (requirement: "do not apply invalid proposals").
          - `ready_for_application` is `True` but the validated
            proposal's own `proposed_changes` is empty (e.g. a
            `NO_CHANGE_NEEDED` proposal that still validated cleanly)
            -> `application_performed=False`, `application=None`.
            There is nothing to apply.
          - `ready_for_application` is `True` and at least one change
            is present -> exactly the *first* entry in
            `proposed_changes` is applied (requirement: "apply exactly
            one validated proposal change per operation" - a
            multi-change proposal is never applied all at once by this
            method; a caller wanting a later change applies it on a
            later call, against the freshly re-validated proposal that
            call produces) via
            `self._proposal_applier.apply_change(plan, change)`, where
            `plan` is looked up fresh from `self._plan_manager` (the
            same already-validated `plan_id`) -
            `application_performed=True`, `application` is that call's
            own structured result, returned unchanged (requirement:
            "return the existing structured application result").

        Recording (requirement: "record the successful application
        using the existing proposal history system if that integration
        already exists"): whenever a change is actually applied (the
        third case above), the result is also handed to
        `self.proposal_history.record(...)` - but only when this loop
        was constructed with a `proposal_history` (see `__init__`).
        `ProposalHistory.record` itself already only ever stores a
        result that reports success (see proposal_history.py) - this
        method never re-checks that a second way, and a rejected/failed
        `apply_change` result (an unsupported change type, an unknown
        target step, a duplicate, a cycle, and so on) is simply never
        recorded, exactly as `ProposalHistory.record` already handles
        on its own. Omitting `proposal_history` is always safe - the
        change is still applied, and its structured result is still
        returned, just not additionally recorded anywhere.

        Purely a connecting step, not a new proposal-application
        system: the only mutation this method ever causes is the exact
        one `ProposalApplier.apply_change` itself already performs on
        the single target step the one applied change names - every
        existing safety/validation rule `ProposalApplier`/
        `AdaptivePlanProposal.validate_proposal` already enforce is
        preserved completely unchanged. Never executes a step, a
        capability, or another Plan-changing operation of its own -
        applying a change here never triggers `run()`/`execute_plan`,
        and this method itself never calls itself or `run()`
        (requirement: "do not execute another step automatically after
        applying the change"). `run()` itself never calls this
        automatically, same "explicitly invoked by a caller" convention
        every other `request_*`/`apply_*` method on this loop already
        follows.

        Raises `ValueError` when a change actually needs to be applied
        (`ready_for_application` is `True` and at least one change is
        present) but this `AgentLoop` was never supplied a
        `proposal_applier` (via `__init__`) - same "raise only when the
        missing collaborator is actually needed" convention
        `request_proposal`/`request_correction_analysis` already
        follow - or, before that, only in the same, already-documented
        cases `request_correction_validation` itself already raises
        for."""
        correction_validation = self.request_correction_validation(goal_id, plan_id, test_result)
        if not correction_validation["ready_for_application"]:
            return {
                "correction_validation": correction_validation,
                "application_performed": False,
                "application": None,
            }

        proposal = correction_validation["correction_proposal"]["proposal"]
        changes = proposal.get("proposed_changes") or []
        if not changes:
            return {
                "correction_validation": correction_validation,
                "application_performed": False,
                "application": None,
            }

        if self._proposal_applier is None:
            raise ValueError(
                "AgentLoop.apply_correction_proposal requires this AgentLoop to "
                "have been constructed with a ProposalApplier (see the "
                "proposal_applier argument to __init__)."
            )

        # Apply exactly one validated proposal change per operation -
        # the first (and, for most correction proposals, only) change
        # the validated proposal carries.
        change = changes[0]
        plan = self._plan_manager.get_plan(plan_id)
        application = self._proposal_applier.apply_change(plan, change)

        if self.proposal_history is not None:
            self.proposal_history.record(
                proposal.get("proposal_id"),
                change.get("change_type"),
                change.get("target_step_id"),
                application,
            )

        return {
            "correction_validation": correction_validation,
            "application_performed": True,
            "application": application,
        }

    def apply_correction_and_reexecute(self, goal_id, plan_id, test_result, capability_system=None):
        """Connect `apply_correction_proposal` above to this loop's
        existing controlled single-step execution path - the exact
        same `StepExecutionController.execute_step`
        (execution/step_execution_controller.py, shared unchanged via
        `self._controller.step_controller` - the same collaborator
        `execute_next_step` above already calls into) - so that once
        one correction proposal has actually been applied, the one
        `PlanStep` that change targeted can be run again, through the
        existing preparation/capability/dependency/safety gate,
        without inventing a second execution path.

        Always returns:
            {
                "application": <the exact dict
                    apply_correction_proposal(goal_id, plan_id,
                    test_result) itself would return>,
                "reexecution_performed": <bool - True only when this
                    call actually invoked
                    StepExecutionController.execute_step>,
                "reexecution_result": <the exact, unmodified structured
                    dict self._controller.step_controller.execute_step(
                    plan_id, target_step_id,
                    capability_system=capability_system) itself would
                    return, if "reexecution_performed" is True;
                    otherwise None>,
            }

        `"reexecution_performed"`/`"reexecution_result"` are derived
        from nothing but the nested
        `application["application_performed"]`/`["application"]` -
        this method never re-derives whether the correction actually
        applied a second way, and never invents a re-execution
        outcome:
          - `application_performed` is `False` (no proposal was ready
            to apply - see `apply_correction_proposal`) ->
            `reexecution_performed=False`, `reexecution_result=None`.
            Nothing was applied, so there is nothing to re-execute.
          - `application_performed` is `True` but
            `application["success"]` is `False` (the change was
            rejected by `ProposalApplier` - an unsupported change
            type, an unknown target step, a duplicate, a cycle, and so
            on) -> `reexecution_performed=False`,
            `reexecution_result=None`. A *failed* correction
            application never triggers re-execution (requirement: "a
            failed correction application does not trigger
            re-execution") - the affected step is left exactly as it
            was.
          - `application["success"]` is `True` -> exactly the one
            `target_step_id` that successful change actually targeted
            (`application["application"]["target_step_id"]`) is
            refreshed (via the same one-time
            `PlanManager.refresh_plan_step_statuses` call
            `execute_next_step` above already performs before
            selecting a step, reused unchanged here so a step this
            change just unblocked - e.g. a dangling dependency
            `ProposalApplier` just removed - is correctly reclassified
            READY before the same preparation gate below reads its
            status) and then run exactly once via
            `self._controller.step_controller.execute_step(plan_id,
            target_step_id, capability_system=capability_system)` -
            `reexecution_performed=True`, `reexecution_result` is that
            call's own structured result, returned unchanged and kept
            entirely separate from `application` (requirement: "return
            the new execution result separately from the original
            execution result") - this method never merges the two, and
            never overwrites or discards whatever `ExecutionHistory`
            already holds for this step's earlier attempt(s); the new
            `ExecutionResult` `execute_step` records is simply another,
            later entry alongside them, exactly as `ExecutionHistory`
            already accumulates every attempt (see
            execution/execution_history.py).

        Re-executes only the affected step (requirement: "re-execute
        only the affected step" / "do not execute unrelated steps"):
        `execute_step` is always called with exactly the one
        `target_step_id` the successful application reported - never
        `execute_next_step`'s own next-*ready*-step selection, which
        could legitimately choose a *different* step if more than one
        happens to be READY right now. No other `PlanStep` in this
        Plan is ever inspected, prepared, or run by this method.

        Allows at most one re-execution per call (requirement: "allow
        at most one re-execution for that correction operation" / "do
        not automatically retry more than once"): this method calls
        `execute_step` at most once, full stop - it never loops, never
        calls itself, and never calls `execute_step` a second time
        within the same call regardless of whether the first (and
        only) attempt COMPLETED or FAILED. A caller wanting to correct
        and re-execute again still has to explicitly call this method
        again, against a freshly generated, freshly re-validated
        correction proposal that later call produces on its own - this
        method itself implements no automatic retry loop of any kind.
        `run()` itself never calls this automatically, same
        "explicitly invoked by a caller" convention every other
        `request_*`/`apply_*` method on this loop already follows.

        Creates no new execution system and modifies no existing one:
        the only two calls this method ever makes beyond
        `apply_correction_proposal` are the exact same
        `PlanManager.refresh_plan_step_statuses` and
        `StepExecutionController.execute_step` calls
        `execute_next_step` above already makes, reused completely
        unchanged - same preparation gate
        (`StepExecutionPreparation.prepare_with_context`), same
        `ExecutionEngine.execute_capability_step`, same
        `ExecutionResult`/`ExecutionHistory`/`ExecutionEventLog`
        recording, same COMPLETED/FAILED status transition, and same
        `ExecutionResult` model (untouched) that every other execution
        path in this project already shares. `ProposalApplier`/
        `AdaptivePlanProposal.validate_proposal`'s own safety rules are
        also preserved completely unchanged, since this method never
        touches either - it only ever reads the already-produced
        `application` result `apply_correction_proposal` returns.

        Raises only in the same, already-documented cases
        `apply_correction_proposal` itself already raises for - never
        a new guard of its own."""
        application = self.apply_correction_proposal(goal_id, plan_id, test_result)
        if not application["application_performed"] or not application["application"]["success"]:
            return {
                "application": application,
                "reexecution_performed": False,
                "reexecution_result": None,
            }

        target_step_id = application["application"]["target_step_id"]

        # Same one-time refresh `execute_next_step` already performs
        # before its own selection - reused unchanged here so a step
        # this change just unblocked is correctly reclassified
        # READY/BLOCKED before the preparation gate below reads its
        # status. Skipped for an unknown plan_id (same "never raise
        # for a bad id" convention `execute_next_step` already
        # follows) - `execute_step` below still reports a structured
        # failure for it.
        if self._plan_manager.get_plan(plan_id) is not None:
            self._plan_manager.refresh_plan_step_statuses(plan_id, capability_system)

        # Exactly one call, to the existing, unchanged
        # StepExecutionController - never a second copy of preparation
        # or capability-execution logic, and never another step
        # executed within this same call (requirement: "re-execute
        # only the affected step").
        reexecution_result = self._controller.step_controller.execute_step(
            plan_id, target_step_id, capability_system=capability_system,
        )

        self._log_event(
            EVENT_AGENT_EXECUTION_COMPLETED, plan_id,
            f"Corrected step re-executed: {target_step_id} "
            f"({'succeeded' if reexecution_result['success'] else 'failed'}).",
            data={
                "reexecuted": True, "step_id": target_step_id,
                "success": reexecution_result["success"],
            },
            severity=SEVERITY_INFO if reexecution_result["success"] else SEVERITY_ERROR,
        )

        return {
            "application": application,
            "reexecution_performed": True,
            "reexecution_result": reexecution_result,
        }

    def apply_correction_reexecute_and_evaluate(
        self, goal_id, plan_id, test_result, capability_system=None,
    ):
        """Connect `apply_correction_and_reexecute` above to this
        loop's existing evaluation flow - the exact same
        `agent.test_result_evaluation.build_test_evaluation`
        `evaluate_test_result` already exposes, and the exact same
        `GoalCompletionEvaluator.evaluate` `run()` already calls both
        before and after execution - so that once a correction has
        actually been applied and its one affected step re-executed,
        what that re-execution produced is evaluated the same way
        every other result in this project already is, without a
        second, differently-behaving evaluation system of its own.

        Always returns:
            {
                "reexecution": <the exact dict
                    apply_correction_and_reexecute(goal_id, plan_id,
                    test_result, capability_system=capability_system)
                    itself would return - "application" and
                    "reexecution_result" preserved completely
                    unmodified and kept separate, exactly as that
                    method already documents>,
                "evaluation_performed": <bool - True only when this
                    call actually evaluated a reexecution_result>,
                "final_evaluation": <
                    {
                        "reexecution_test_evaluation": <the exact
                            dict evaluate_test_result(...) itself
                            would return, called with the entry under
                            reexecution_result["output"] keyed by the
                            existing python_test_runner_capability.
                            CAPABILITY_NAME - i.e. the same
                            {capability_name: handler_return_value}
                            output shape StepExecutionController/
                            ExecutionEngine already document - or None
                            if that key isn't present>,
                        "goal_evaluation": <the exact dict
                            self._evaluator.evaluate(goal_id, plan_id)
                            itself would return, read fresh - i.e.
                            reflecting the Plan/step state right after
                            the re-execution above>,
                    }
                    if "evaluation_performed" is True; otherwise
                    None>,
            }

        `"evaluation_performed"`/`"final_evaluation"` are derived from
        nothing but the nested
        `reexecution["reexecution_performed"]` - this method never
        re-derives whether a re-execution actually happened a second
        way, and never invents an evaluation outcome:
          - `reexecution_performed` is `False` (no proposal was ready
            to apply, or the application itself failed - see
            `apply_correction_and_reexecute`) -> `evaluation_performed
            =False`, `final_evaluation=None`. Nothing was re-executed,
            so there is nothing new to evaluate.
          - `reexecution_performed` is `True` -> exactly two existing,
            already-read-only evaluators are consulted, once each:
            `self.evaluate_test_result(...)` (reusing
            `build_test_evaluation`/`classify_test_result` completely
            unchanged - the same classifier
            `evaluate_test_result`/`evaluate_correction_decision`
            above already use, called with the entry under
            `reexecution_result["output"]` keyed by the existing
            `python_test_runner_capability.CAPABILITY_NAME`, so a
            re-executed test-running step's new `python_test_runner`
            output is classified PASSED/FAILED/TIMEOUT/INVALID exactly
            as the original `test_result` that triggered this
            correction was) and `self._evaluator.evaluate(goal_id,
            plan_id)` (the exact same `GoalCompletionEvaluator`
            instance `run()` itself already evaluates through both
            before and after every execution - never a second,
            disagreeing evaluator, and never one constructed fresh
            here). Neither call takes anything from
            `reexecution_result` beyond what it already documents
            (`"output"`); `goal_evaluation` reads the Plan's current,
            already-updated state exactly as `run()`'s own
            post-execution evaluation already does, never a value
            derived or guessed at here.

        Preserves the original execution result and the re-execution
        result completely separately: `"reexecution"` is the exact,
        unmodified dict `apply_correction_and_reexecute` returns -
        `application["application"]` (the original, already-applied
        correction) and `reexecution_result` (the new attempt) are
        never merged, copied-with-changes, or summarized away by this
        method; `"final_evaluation"` is added alongside them as a
        third, separate field, never overwriting either.

        Applies no second correction and re-executes nothing a second
        time (requirement: "do not automatically apply another
        correction" / "do not automatically re-execute the step
        again"): this method calls `apply_correction_and_reexecute`
        exactly once - which itself already calls
        `apply_correction_proposal`/`StepExecutionController.
        execute_step` at most once each, per that method's own
        contract - and never loops, never calls itself, and never
        calls either evaluator more than once. A caller wanting to
        correct and evaluate again still has to explicitly call this
        method again, against a freshly generated, freshly
        re-validated correction proposal that later call produces on
        its own - same "explicitly invoked by a caller, no automatic
        retry loop" convention `apply_correction_and_reexecute` itself
        already documents. `run()` itself never calls this
        automatically, same convention every other `request_*`/
        `apply_*`/`evaluate_*` method on this loop already follows.

        Creates no new evaluation system and modifies no existing one:
        the only two calls this method ever makes beyond
        `apply_correction_and_reexecute` are `self.evaluate_test_result`
        (already defined above, itself a thin, unmodified wrapper
        around `agent.test_result_evaluation.build_test_evaluation`)
        and `self._evaluator.evaluate` (the existing
        `GoalCompletionEvaluator`, itself untouched by this method).
        Both are already-existing, already-read-only evaluators reused
        exactly as `evaluate_test_result`/`run()` already use them.

        Every existing iteration/safety limit is preserved unchanged:
        this method never touches `max_iterations`, never calls
        `run()`, and adds no loop, no recursion, and no new bound of
        its own - the only execution it can ever trigger is the single
        `StepExecutionController.execute_step` call already bounded,
        gated, and accounted for entirely inside
        `apply_correction_and_reexecute`/`apply_correction_proposal`.

        Raises only in the same, already-documented cases
        `apply_correction_and_reexecute` itself already raises for -
        never a new guard of its own."""
        reexecution = self.apply_correction_and_reexecute(
            goal_id, plan_id, test_result, capability_system=capability_system,
        )
        if not reexecution["reexecution_performed"]:
            return {
                "reexecution": reexecution,
                "evaluation_performed": False,
                "final_evaluation": None,
            }

        reexecution_result = reexecution["reexecution_result"]
        # `reexecution_result["output"]` is always the existing
        # `{capability_name: handler_return_value}` shape
        # `StepExecutionController.execute_step`/`ExecutionEngine.
        # execute_capability_step` already document (never a raw
        # test-runner result by itself, even for a step with only one
        # required capability) - so the one entry under the existing
        # `python_test_runner_capability.CAPABILITY_NAME` key (if any
        # - a re-executed step need not even use that capability) is
        # what gets handed to the exact same `evaluate_test_result`
        # used everywhere else in this loop; a step whose output has
        # no such entry (`None`) is classified `RESULT_INVALID` by
        # `classify_test_result` itself, exactly as any other
        # not-a-test-runner-result input already is - never guessed
        # at as PASSED/FAILED.
        output = reexecution_result["output"]
        test_output = (
            output.get(_PYTHON_TEST_RUNNER_CAPABILITY_NAME)
            if isinstance(output, dict) else None
        )
        reexecution_test_evaluation = self.evaluate_test_result(test_output)
        goal_evaluation = self._evaluator.evaluate(goal_id, plan_id)

        self._log_event(
            EVENT_AGENT_EVALUATION_COMPLETED, plan_id,
            f"Re-execution evaluated: "
            f"{reexecution_test_evaluation['classification']} "
            f"(goal_status={goal_evaluation['status']}).",
            data={
                "phase": "post_reexecution",
                "step_id": reexecution_result["step_id"],
                "test_classification": reexecution_test_evaluation["classification"],
                "goal_status": goal_evaluation["status"],
            },
        )

        return {
            "reexecution": reexecution,
            "evaluation_performed": True,
            "final_evaluation": {
                "reexecution_test_evaluation": reexecution_test_evaluation,
                "goal_evaluation": goal_evaluation,
            },
        }

    # ------------------------------------------------------------------
    # Controlled agent loop
    # ------------------------------------------------------------------
    def run(self, goal_id, plan_id, max_iterations=1):
        """Coordinate Goal evaluation and existing Plan execution for
        one Goal/Plan pair, in a bounded, deterministic loop.

        `max_iterations` must be a finite, positive integer (default
        `1`); anything else (a bool, a float, zero, a negative number,
        `None`, `float("inf")`, ...) raises `ValueError` before
        anything is evaluated or executed - same "never silently
        accept junk" convention `PlanExecutionController.execute_plan`
        already applies to its own `max_steps_per_run` (requirement 8:
        "max_iterations must always be finite and validated").

        Step 0 - guards, before a single evaluation ever happens
        (requirements 1, 2), reusing exactly the same checks
        `GoalCompletionEvaluator.evaluate` itself already performs, in
        the same order:
          1. `goal_id` must name a known Goal (`GoalManager.get_goal`);
          2. `plan_id` must name a known Plan (`PlanManager.get_plan`);
          3. that Plan's own `goal_id` must actually match the
             requested `goal_id`.
        Any failure here returns immediately with `status="invalid"`,
        `success=False`, `iterations=0`, and a structured `error` -
        nothing is ever evaluated or executed (never raises for a bad
        id - same "a query that should always have a structured
        answer" convention the rest of this project's execution-stack
        classes already follow).

        Step 1 - the bounded loop (executed at most `max_iterations`
        times; requirement 9: never unlimited, never recursive - this
        method never calls itself):
          a. evaluate the current Goal state (requirement 3) via
             `GoalCompletionEvaluator.evaluate` - unchanged, read-only;
          b. if the Goal is already SATISFIED, stop immediately without
             executing anything (requirements 4, 13);
          c. if the Goal is FAILED or BLOCKED, stop immediately without
             executing anything - a plan already on record as failed
             is never automatically retried (requirement 11), and a
             plan already on record as blocked is reported as such
             (requirement 12) rather than re-attempted;
          d. otherwise (NOT_SATISFIED / PARTIALLY_SATISFIED / UNKNOWN),
             execute the existing Plan exactly once via
             `PlanExecutionController.execute_plan` (requirement 5) -
             the single existing place a step is actually prepared and
             run; this method never duplicates any of that logic;
          e. if that execution reports failure, stop immediately,
             preserving the failure and never retrying it in this or
             any later iteration (requirement 11);
          f. if that execution reports the Plan is BLOCKED, stop and
             report BLOCKED (requirement 12);
          g. otherwise, evaluate the Goal again (requirement 6) via
             `GoalCompletionEvaluator.evaluate`;
          h. if the Goal is now SATISFIED, stop immediately
             (requirement 13); if it is now FAILED or BLOCKED, stop and
             report that;
          i. otherwise, if the just-completed execution reports
             anything other than PLAN_RUN_WAITING (i.e. the Plan ran to
             completion, or had nothing executable, and the Goal is
             still not satisfied), stop and report NOT_SATISFIED or
             UNKNOWN, based only on what `GoalCompletionEvaluator`
             itself just observed - never inventing another action
             (requirement 14);
          j. otherwise (PLAN_RUN_WAITING: the Plan still contains
             executable, unfinished steps), continue to the next
             iteration only if the iteration budget allows it
             (requirement 10) - this method never creates a new Plan
             to keep going (requirement: "do not create a new plan
             automatically").

        If the loop exhausts `max_iterations` while the Plan still had
        executable, unfinished steps remaining, this returns
        `status="max_iterations_reached"` (`success=True` - running
        out of budgeted iterations is an honest, structured stopping
        point, not a failure of the loop itself) so a caller can choose
        to call `run()` again with a fresh, explicit budget.

        Returns a dict (requirement 7):
            {
                "success": bool,
                "goal_id": str,
                "plan_id": str,
                "status": str,          # one of ALL_AGENT_LOOP_STATUSES
                "iterations": int,
                "goal_status": str,     # GoalCompletionEvaluator's own
                                         # STATE_* vocabulary, from the
                                         # most recent evaluation
                "executed_steps": [step_id, ...],   # every step this
                                                     # call itself ran,
                                                     # across every
                                                     # iteration, in order
                "completed_steps": [step_id, ...],  # from the most
                "failed_steps": [step_id, ...],     # recent Goal
                "blocked_steps": [step_id, ...],    # evaluation
                "outputs": {step_id: output, ...},
                "evidence": [str, ...],
                "warnings": [str, ...],
                "error": str or None,
                "learning_context": [dict, ...],  # every existing
                                                   # LearningRecord.to_dict()
                                                   # already stored (via
                                                   # ExecutionLearning/
                                                   # LearningRecordStore)
                                                   # for this exact
                                                   # plan_id, read once
                                                   # before this call's
                                                   # own loop starts, in
                                                   # the same order
                                                   # LearningRecordStore.
                                                   # get_all() returns
                                                   # them; [] when no
                                                   # learning_record_store
                                                   # was supplied to this
                                                   # AgentLoop, or none
                                                   # match yet
                "next_step": dict or None,  # when the Goal is *not*
                                             # satisfied, the next
                                             # READY, executable step
                                             # `PlanExecutionCoordinator.
                                             # get_next_ready_step`
                                             # identifies right now -
                                             # {"step_id", "executable",
                                             # "reason", "warnings"} -
                                             # identified only, never
                                             # executed by this call;
                                             # None when the Goal is
                                             # already satisfied (see
                                             # `_finish`/
                                             # `_identify_next_step`
                                             # below) or when this call
                                             # never got past Step 0's
                                             # guards
            }
        """
        if not isinstance(max_iterations, int) or isinstance(max_iterations, bool) \
                or max_iterations < 1:
            raise ValueError("max_iterations must be a positive integer (>= 1).")

        self._log_event(
            EVENT_AGENT_LOOP_STARTED, plan_id,
            f"AgentLoop starting for goal_id={goal_id!r}, plan_id={plan_id!r} "
            f"(max_iterations={max_iterations}).",
            data={"goal_id": goal_id, "plan_id": plan_id, "max_iterations": max_iterations},
        )

        # Step 0 - guards (requirements 1, 2), same order/checks
        # GoalCompletionEvaluator.evaluate itself already applies.
        goal = self._goal_manager.get_goal(goal_id)
        if goal is None:
            return self._fail_invalid(goal_id, plan_id, f"No Goal found for goal_id {goal_id!r}.")

        plan = self._plan_manager.get_plan(plan_id)
        if plan is None:
            return self._fail_invalid(goal_id, plan_id, f"No Plan found for plan_id {plan_id!r}.")

        if plan.goal_id != goal_id:
            return self._fail_invalid(
                goal_id, plan_id,
                f"Plan {plan_id!r} belongs to goal_id {plan.goal_id!r}, not the "
                f"requested goal_id {goal_id!r}; refusing to run a plan against a "
                "goal it isn't attached to.",
            )

        # Learning (requirement: "before executing an existing plan,
        # allow AgentLoop to read relevant existing learning records
        # for the current goal or plan") - read once, here, after the
        # Plan is confirmed to actually belong to this Goal and before
        # this call's own loop (and therefore every
        # PlanExecutionController.execute_plan call within it) ever
        # starts. Purely observational (see _relevant_learning_records
        # above) - nothing below ever branches on this.
        learning_context = self._relevant_learning_records(plan_id)

        executed_steps = []
        outputs = {}
        # Connect execution output back into AgentLoop state (Prompt
        # 313): accumulated the same way `outputs`/`executed_steps`
        # already are - across this call's own iterations, never
        # reset mid-loop - so a completed step's output (together with
        # its own execution_id) recorded on one iteration is still
        # present, unmodified, on every later iteration and in the
        # final result (see `_step_execution_outputs` above).
        step_outputs = {}
        evidence = []
        warnings = []
        last_evaluation = None
        iterations = 0

        # Step 1 - the bounded loop (requirement 9: finite, never
        # recursive; at most max_iterations passes).
        while iterations < max_iterations:
            iterations += 1
            self._log_event(
                EVENT_AGENT_ITERATION_STARTED, plan_id,
                f"Iteration {iterations} started.",
                data={"iteration": iterations},
            )

            # (a) Evaluate the current Goal state before executing
            # anything (requirement 3).
            evaluation = self._evaluator.evaluate(goal_id, plan_id)
            last_evaluation = evaluation
            self._merge(evidence, evaluation["evidence"])
            self._merge(warnings, evaluation["warnings"])
            goal_status = evaluation["status"]

            self._log_event(
                EVENT_AGENT_EVALUATION_COMPLETED, plan_id,
                f"Evaluation completed: {goal_status}.",
                data={"iteration": iterations, "goal_status": goal_status, "phase": "pre_execution"},
            )

            # (b) Already SATISFIED - stop immediately, execute nothing
            # (requirements 4, 13).
            if goal_status == STATE_SATISFIED:
                return self._finish(
                    True, STATUS_SATISFIED, goal_id, plan_id, iterations, goal_status,
                    executed_steps, last_evaluation, outputs, evidence, warnings, None,
                    "Goal already satisfied; stopping without executing anything.",
                    learning_context, step_outputs=step_outputs,
                )

            # (c) Already FAILED/BLOCKED on record - never automatically
            # retried (requirement 11); report blocked as such
            # (requirement 12).
            if goal_status == STATE_FAILED:
                error = "Goal evaluation reports a failed plan; stopping without retry."
                return self._finish(
                    False, STATUS_FAILED, goal_id, plan_id, iterations, goal_status,
                    executed_steps, last_evaluation, outputs, evidence, warnings, error, error,
                    learning_context, step_outputs=step_outputs,
                )
            if goal_status == STATE_BLOCKED:
                return self._finish(
                    True, STATUS_BLOCKED, goal_id, plan_id, iterations, goal_status,
                    executed_steps, last_evaluation, outputs, evidence, warnings, None,
                    "Goal evaluation reports the plan is blocked; stopping.",
                    learning_context, step_outputs=step_outputs,
                )

            # (d) Not satisfied yet - execute the existing Plan exactly
            # once through the existing PlanExecutionController
            # (requirement 5). Never a second copy of this logic.
            exec_result = self._controller.execute_plan(plan_id)
            executed_steps.extend(exec_result["executed_steps"])
            for step_id, output in exec_result["outputs"].items():
                outputs[step_id] = output
            # Connect this iteration's own completed-step output(s)
            # back into AgentLoop state, keyed by step_id and carrying
            # each one's own execution_id (Prompt 313) - available,
            # unmodified, from this point on to every later iteration
            # of this same `while` loop, and in the final result.
            step_outputs.update(self._step_execution_outputs(exec_result))
            self._merge(warnings, exec_result["warnings"])

            self._log_event(
                EVENT_AGENT_EXECUTION_COMPLETED, plan_id,
                f"Execution completed: {exec_result['status']}.",
                data={
                    "iteration": iterations,
                    "plan_status": exec_result["status"],
                    "success": exec_result["success"],
                    "executed_steps": list(exec_result["executed_steps"]),
                },
            )

            # (e)/(f)/(g) Evaluate the Goal again now that execution has
            # happened (requirement 6) - unconditionally, whether the
            # execution itself succeeded or failed, so the reported
            # completed_steps/failed_steps/blocked_steps always reflect
            # what the Plan's steps actually look like right now.
            post_eval = self._evaluator.evaluate(goal_id, plan_id)
            last_evaluation = post_eval
            self._merge(evidence, post_eval["evidence"])
            self._merge(warnings, post_eval["warnings"])
            post_status = post_eval["status"]

            self._log_event(
                EVENT_AGENT_EVALUATION_COMPLETED, plan_id,
                f"Evaluation completed: {post_status}.",
                data={"iteration": iterations, "goal_status": post_status, "phase": "post_execution"},
            )

            # (e) Execution failed - stop, preserve the failure, no
            # automatic retry (requirement 11).
            if not exec_result["success"]:
                return self._finish(
                    False, STATUS_FAILED, goal_id, plan_id, iterations, post_status,
                    executed_steps, last_evaluation, outputs, evidence, warnings,
                    exec_result["error"],
                    "Plan execution failed; stopping without automatic retry.",
                    learning_context, step_outputs=step_outputs,
                )

            # (f) Execution reports the plan is blocked - stop and
            # report BLOCKED (requirement 12).
            if exec_result["status"] == PLAN_RUN_BLOCKED:
                return self._finish(
                    True, STATUS_BLOCKED, goal_id, plan_id, iterations, post_status,
                    executed_steps, last_evaluation, outputs, evidence, warnings, None,
                    "Plan execution reports the plan is blocked; stopping.",
                    learning_context, step_outputs=step_outputs,
                )

            # (h) SATISFIED/FAILED/BLOCKED after execution - stop.
            if post_status == STATE_SATISFIED:
                return self._finish(
                    True, STATUS_SATISFIED, goal_id, plan_id, iterations, post_status,
                    executed_steps, last_evaluation, outputs, evidence, warnings, None,
                    "Goal satisfied after execution; stopping.",
                    learning_context, step_outputs=step_outputs,
                )
            if post_status == STATE_FAILED:
                error = (
                    "Goal evaluation reports a failed plan after execution; "
                    "stopping without retry."
                )
                return self._finish(
                    False, STATUS_FAILED, goal_id, plan_id, iterations, post_status,
                    executed_steps, last_evaluation, outputs, evidence, warnings, error, error,
                    learning_context, step_outputs=step_outputs,
                )
            if post_status == STATE_BLOCKED:
                return self._finish(
                    True, STATUS_BLOCKED, goal_id, plan_id, iterations, post_status,
                    executed_steps, last_evaluation, outputs, evidence, warnings, None,
                    "Goal evaluation reports the plan is blocked after execution; stopping.",
                    learning_context, step_outputs=step_outputs,
                )

            # (i) Goal still not satisfied, and this run's execution had
            # nothing left to wait on (PLAN_RUN_COMPLETED with an
            # unsatisfied/unknown Goal - e.g. an empty Plan - or
            # PLAN_RUN_FAILED, already handled above) - report the
            # observed state, never invent another action
            # (requirement 14).
            if exec_result["status"] != PLAN_RUN_WAITING:
                final_status = STATUS_UNKNOWN if post_status == STATE_UNKNOWN else STATUS_NOT_SATISFIED
                return self._finish(
                    True, final_status, goal_id, plan_id, iterations, post_status,
                    executed_steps, last_evaluation, outputs, evidence, warnings, None,
                    "No executable steps remain; stopping without inventing further action.",
                    learning_context, step_outputs=step_outputs,
                )

            # (j) PLAN_RUN_WAITING - the Plan still contains executable,
            # unfinished steps (requirement 10). Continue only if the
            # iteration budget allows another pass; the `while` guard
            # above enforces that on the next loop check. Never creates
            # a new Plan to keep going.

        # The loop exhausted `max_iterations` while the Plan still had
        # executable, unfinished steps remaining (the only way to reach
        # here without an earlier `return`).
        final_goal_status = last_evaluation["status"] if last_evaluation else STATE_UNKNOWN
        final_status = (
            STATUS_UNKNOWN if final_goal_status == STATE_UNKNOWN else STATUS_MAX_ITERATIONS_REACHED
        )
        return self._finish(
            True, final_status, goal_id, plan_id, iterations, final_goal_status,
            executed_steps, last_evaluation, outputs, evidence, warnings, None,
            f"max_iterations ({max_iterations}) reached with executable steps still "
            "remaining; stopping.",
            learning_context, step_outputs=step_outputs,
        )
