"""
Deterministic Plan Builder (Prompt 681)
=========================================
Converts an already-prepared `RequestContext` (planning/request_context.py) into a structured, UNEXECUTED
`Plan` (planning/plan.py):

    RequestContext -> build_plan_from_context() -> PlanBuildResult(plan, validation | failures)
        -> (existing) validate_plan / prepare_execution_handoff

PLANNING vs EXECUTION: this module only describes work. It imports no execution/engine/handler code and no
os/subprocess/socket/network module, opens no file, calls no tool or capability, writes no knowledge,
memory, goal, plan-store or conversation state, and never mutates the RequestContext it is given (it does
not even attach the plan; the caller decides). Every produced step is `pending`, the plan is marked
`metadata["phase"] == "planning"`, `executed=False`, `execution_authorized=False`, and no capability is
ever invented (steps require none; capability-bearing plans are a later, explicitly approved stage).

DETERMINISM: same context content -> identical plan (ids come from a digest of normalized request + intent,
step ids are `step-001`, `step-002`, ... in construction order, `created_at` is a fixed sentinel). An invalid
or incomplete context (wrong type, empty request, missing normalized text/intent/reasoning, a persistent
context, or any BLOCKING information gap) yields a `rejected` result with ordered failure codes and NO plan -
a plan is never guessed or repaired.

Step order: (1) confirm request + intent, (2) one review step per CURRENT knowledge record, (3) one step per
NON-blocking information gap, (4) prepare the response, depending on every earlier step.

DEPENDENCIES (Prompt 682): a step declares dependencies through the existing `PlanStep.dependencies` list. Real
dependencies only: review and gap steps need the confirmed request; the response needs every earlier step; review
and gap steps do NOT depend on each other. `validate_step_dependencies()` checks a Plan (or a step list) and
REPORTS - never repairs - unknown ids, self-dependencies, duplicate dependencies, forward references, unordered
lists, non-list dependencies and cycles, in deterministic order. The builder runs it before creating the plan
and rejects with `INVALID_DEPENDENCY_GRAPH` (no plan) when it fails.

ORDERING (Prompt 683): `order_plan_steps(plan_or_steps)` returns a `PlanOrderResult` with a stable topological order
(Kahn; among ready steps the earliest DECLARED one goes first, so independent steps keep their declared order and the
same input always yields the same order). The graph is gated by `validate_step_dependencies()`: an invalid graph is
rejected (`INVALID_DEPENDENCY_GRAPH`, no order) and never repaired or silently reordered. The input is never mutated;
ordered steps are fresh copies and nothing is executed.

STEP STATES (Prompt 684): `validate_plan_step_states(plan)` is a pure, read-only consistency check of step states and
the plan's execution flags (`metadata["executed"]`, `metadata["execution_authorized"]`). Supported step states here:
`pending` (the only state builder plans use), `in_progress`, `completed`, `failed`; the last three imply that
execution happened. Invalid input is REPORTED with stable codes in deterministic order - never normalized or repaired.
Nothing is executed, written or mutated.

READINESS (Prompt 686): `get_ready_plan_steps(plan)` is a pure, read-only query returning the steps that are ready to
be picked up NOW, judged only from declared dependencies and current step states. A step is ready only when it is
`pending`, has no recorded output (not executed), and every declared dependency exists and is `completed`
(pending / in_progress / failed dependencies block it). Plan-level `execution_authorized` (Prompt 688) is permission
to execute, NOT evidence of execution: it neither makes a pending step unready nor marks anything executed - only
step state/output is evidence of execution - so an authorized plan still reports its unexecuted ready steps. Invalid input
(not a Plan, invalid dependency graph, unsupported step state, non-boolean execution flags) is REJECTED with stable
codes, never guessed or repaired. Ready steps are fresh copies in deterministic plan order. It executes nothing,
authorizes nothing and mutates nothing; flags must be real booleans but their consistency with step states is
Prompt 684's job (`validate_plan_step_states`), reused rather than duplicated.

PROGRESS (Prompt 687): `evaluate_plan_progress(plan)` is a pure, read-only summary built ON TOP of
`get_ready_plan_steps` (which supplies the graph/flag/state validation and the ready ids - nothing is re-implemented).
Rules: counts per state; `complete` only when the plan has steps and EVERY step is `completed` (an empty plan is
valid, all counts 0, NOT complete, NOT blocked); `blocked` when at least one pending step has a `failed` step among
its transitive dependencies (a terminal condition) AND nothing can still move: no ready ids, no in_progress step and
no pending step whose dependencies are all completed. A plan with ready steps is therefore never blocked. Invalid
input is rejected with the readiness failures, never repaired. Nothing is executed, authorized or mutated.
"""

import hashlib

from planning.plan import (ALL_STATUSES, Plan, PlanStep, STATUS_COMPLETED, STATUS_FAILED, STATUS_IN_PROGRESS,
                           STATUS_PENDING)
from planning.plan_validation import _find_cycle, validate_plan
from planning.request_context import RequestContext

STATUS_PLANNED = "planned"
STATUS_REJECTED = "rejected"

FAIL_INVALID_CONTEXT = "INVALID_CONTEXT"
FAIL_EMPTY_REQUEST = "EMPTY_REQUEST"
FAIL_INCOMPLETE_CONTEXT = "INCOMPLETE_CONTEXT"
FAIL_PERSISTENT_CONTEXT = "PERSISTENT_CONTEXT"
FAIL_BLOCKING_GAPS = "BLOCKING_INFORMATION_GAPS"
FAIL_PLAN_INVALID = "GENERATED_PLAN_INVALID"
FAIL_DEPENDENCY_GRAPH = "INVALID_DEPENDENCY_GRAPH"

DEP_DUPLICATE_STEP_ID = "DUPLICATE_STEP_ID"
DEP_INVALID_DEPENDENCIES = "INVALID_DEPENDENCIES"
DEP_UNKNOWN = "UNKNOWN_DEPENDENCY"
DEP_SELF = "SELF_DEPENDENCY"
DEP_DUPLICATE = "DUPLICATE_DEPENDENCY"
DEP_FORWARD = "FORWARD_DEPENDENCY"
DEP_UNORDERED = "UNORDERED_DEPENDENCIES"
DEP_CYCLE = "DEPENDENCY_CYCLE"

PLAN_CREATED_AT = "1970-01-01T00:00:00+00:00"   # fixed sentinel: planning never depends on the clock
PLANNER_NAME = "deterministic_plan_builder"


class PlanBuildResult:
    __slots__ = ("status", "plan", "validation", "dependency_validation", "failures", "executed",
                 "execution_authorized")

    def __init__(self):
        self.status = STATUS_REJECTED
        self.plan = None
        self.validation = None
        self.dependency_validation = None
        self.failures = []
        self.executed = False
        self.execution_authorized = False

    @property
    def ok(self):
        return self.status == STATUS_PLANNED

    def codes(self):
        return [f["code"] for f in self.failures]

    def to_dict(self):
        return {
            "status": self.status,
            "plan": None if self.plan is None else self.plan.to_dict(),
            "validation": None if self.validation is None else self.validation.to_dict(),
            "dependency_validation": (None if self.dependency_validation is None
                                      else self.dependency_validation.to_dict()),
            "failures": [dict(f) for f in self.failures],
            "executed": self.executed,
            "execution_authorized": self.execution_authorized,
        }


def _failure(code, message, **details):
    item = {"code": code, "message": message}
    item.update(details)
    return item


def _reject(result, failures):
    result.status = STATUS_REJECTED
    result.plan = None
    result.validation = None
    result.dependency_validation = None
    result.failures = failures
    return result


def _context_failures(ctx):
    """Ordered failures making `ctx` unusable for planning ([] when it is usable)."""
    if not isinstance(ctx, RequestContext):
        return [_failure(FAIL_INVALID_CONTEXT, "Not a RequestContext; nothing to plan.")]
    failures = []
    normalized = ctx.normalized_request
    if not isinstance(normalized, str) or not normalized.strip():
        failures.append(_failure(FAIL_EMPTY_REQUEST, "The request is empty."))
    else:
        missing = []
        if not isinstance(ctx.original_input, str):
            missing.append("original_input")
        if not isinstance(ctx.intent, str) or not ctx.intent.strip():
            missing.append("intent")
        if ctx.reasoning is None:
            missing.append("reasoning")
        if missing:
            failures.append(_failure(FAIL_INCOMPLETE_CONTEXT,
                                     "The request context is incomplete: " + ", ".join(missing) + ".",
                                     missing=missing))
    if ctx.persistent:
        failures.append(_failure(FAIL_PERSISTENT_CONTEXT, "A request context must never be persistent."))
    blocking = [{"code": g.get("code"), "message": g.get("message")} for g in ctx.information_gaps
                if isinstance(g, dict) and g.get("blocking")]
    if blocking:
        failures.append(_failure(FAIL_BLOCKING_GAPS, "Blocking information gaps prevent planning.",
                                 gaps=blocking))
    return failures


class DependencyValidationResult:
    __slots__ = ("valid", "issues", "graph", "ordered_step_ids")

    def __init__(self):
        self.valid = False
        self.issues = []
        self.graph = {}              # step id -> its dependencies, in step order (as declared)
        self.ordered_step_ids = []   # step order, only when valid

    def codes(self):
        return [i["code"] for i in self.issues]

    def has(self, code):
        return code in self.codes()

    def to_dict(self):
        return {
            "valid": self.valid,
            "issues": [dict(i) for i in self.issues],
            "graph": {k: list(v) for k, v in self.graph.items()},
            "ordered_step_ids": list(self.ordered_step_ids),
        }


def validate_step_dependencies(plan_or_steps):
    """Read-only check of step dependencies for a `Plan` or a list of `PlanStep`. Rules: every dependency is
    a string naming a DIFFERENT step of the same plan that comes EARLIER, appears once, and the list is in
    step order; no cycles. Issues are reported in deterministic order (step order, then list position, then
    the cycle); nothing is repaired, reordered or mutated. Never raises."""
    res = DependencyValidationResult()
    steps = getattr(plan_or_steps, "steps", plan_or_steps)
    if not isinstance(steps, (list, tuple)):
        res.issues.append(_failure(DEP_INVALID_DEPENDENCIES, "Not a Plan or a list of steps."))
        return res

    index = {}
    ids = []
    for step in steps:
        sid = getattr(step, "step_id", None)
        if not isinstance(sid, str) or not sid.strip():
            res.issues.append(_failure(DEP_INVALID_DEPENDENCIES, "A step has an empty or non-string id."))
        elif sid in index:
            res.issues.append(_failure(DEP_DUPLICATE_STEP_ID, f"Duplicate step id: {sid}.", step_id=sid))
        else:
            index[sid] = len(ids)
            ids.append(sid)
    if res.issues:
        return res

    edges = {}
    for step in steps:
        sid = step.step_id
        deps = getattr(step, "dependencies", None)
        if not isinstance(deps, list):
            res.issues.append(_failure(DEP_INVALID_DEPENDENCIES, f"Step {sid} dependencies are not a list.",
                                       step_id=sid))
            edges[sid] = []
            continue
        res.graph[sid] = list(deps)
        seen, clean = set(), []
        for dep in deps:
            if not isinstance(dep, str) or dep not in index:
                res.issues.append(_failure(DEP_UNKNOWN, f"Step {sid} depends on unknown step {dep!r}.",
                                           step_id=sid, dependency=dep))
            elif dep == sid:
                res.issues.append(_failure(DEP_SELF, f"Step {sid} depends on itself.",
                                           step_id=sid, dependency=dep))
            elif dep in seen:
                res.issues.append(_failure(DEP_DUPLICATE, f"Step {sid} lists dependency {dep} more than once.",
                                           step_id=sid, dependency=dep))
            else:
                seen.add(dep)
                clean.append(dep)
                if index[dep] > index[sid]:
                    res.issues.append(_failure(DEP_FORWARD, f"Step {sid} depends on later step {dep}.",
                                               step_id=sid, dependency=dep))
        if clean != sorted(clean, key=index.__getitem__):
            res.issues.append(_failure(DEP_UNORDERED, f"Step {sid} dependencies are not in step order.",
                                       step_id=sid, dependencies=list(deps)))
        edges[sid] = clean

    for sid in ids:
        res.graph.setdefault(sid, [])
    cycle = _find_cycle(ids, edges)
    if cycle:
        res.issues.append(_failure(DEP_CYCLE, "Dependency cycle: " + " -> ".join(cycle) + ".", cycle=cycle))
    res.valid = not res.issues
    if res.valid:
        res.ordered_step_ids = list(ids)
    return res


STATUS_ORDERED = "ordered"


class PlanOrderResult:
    __slots__ = ("status", "ordered_step_ids", "steps", "dependency_validation", "failures", "executed",
                 "execution_authorized")

    def __init__(self):
        self.status = STATUS_REJECTED
        self.ordered_step_ids = []
        self.steps = []              # fresh PlanStep copies in execution-plan order (never the originals)
        self.dependency_validation = None
        self.failures = []
        self.executed = False
        self.execution_authorized = False

    @property
    def ok(self):
        return self.status == STATUS_ORDERED

    def codes(self):
        return [f["code"] for f in self.failures]

    def to_dict(self):
        return {
            "status": self.status,
            "ordered_step_ids": list(self.ordered_step_ids),
            "steps": [s.to_dict() for s in self.steps],
            "dependency_validation": (None if self.dependency_validation is None
                                      else self.dependency_validation.to_dict()),
            "failures": [dict(f) for f in self.failures],
            "executed": self.executed,
            "execution_authorized": self.execution_authorized,
        }


def _copy_step(step):
    return PlanStep(step.step_id, step.description, dependencies=step.dependencies,
                    required_capabilities=step.required_capabilities, expected_output=step.expected_output,
                    status=step.status, input_data=step.input_data, output_data=step.output_data)


def order_plan_steps(plan_or_steps):
    """Stable topological order of a `Plan` (or list of `PlanStep`) whose dependency graph is valid.
    Dependencies always come before their dependents; among steps that are ready at the same time the one
    declared first is placed first. Invalid graphs (see `validate_step_dependencies`) are rejected with
    `INVALID_DEPENDENCY_GRAPH` and no order. Read-only: the input is not mutated, nothing is executed."""
    result = PlanOrderResult()
    check = validate_step_dependencies(plan_or_steps)
    result.dependency_validation = check
    if not check.valid:
        result.failures = [_failure(FAIL_DEPENDENCY_GRAPH, "The step dependencies are invalid; no order produced.",
                                    issues=[dict(i) for i in check.issues])]
        return result

    steps = getattr(plan_or_steps, "steps", plan_or_steps)
    by_id = {s.step_id: s for s in steps}
    declared = [s.step_id for s in steps]
    position = {sid: i for i, sid in enumerate(declared)}
    waiting = {sid: len(check.graph[sid]) for sid in declared}
    dependents = {sid: [] for sid in declared}
    for sid in declared:
        for dep in check.graph[sid]:
            dependents[dep].append(sid)

    order = []
    ready = [sid for sid in declared if waiting[sid] == 0]
    while ready:
        ready.sort(key=position.__getitem__)      # earliest declared first: stable, no hash/set ordering
        current = ready.pop(0)
        order.append(current)
        for nxt in dependents[current]:
            waiting[nxt] -= 1
            if waiting[nxt] == 0:
                ready.append(nxt)
    if len(order) != len(declared):               # unreachable after validation; never guess if it happens
        result.failures = [_failure(FAIL_DEPENDENCY_GRAPH, "The step dependencies could not be fully ordered.")]
        return result

    result.status = STATUS_ORDERED
    result.ordered_step_ids = order
    result.steps = [_copy_step(by_id[sid]) for sid in order]
    return result


# --- step state validation (Prompt 684) ------------------------------------------------------------------
STEP_STATES = (STATUS_PENDING, STATUS_IN_PROGRESS, STATUS_COMPLETED, STATUS_FAILED)
EXECUTION_STATES = (STATUS_IN_PROGRESS, STATUS_COMPLETED, STATUS_FAILED)   # states that imply execution happened

STATE_INVALID_PLAN = "INVALID_PLAN_OBJECT"
STATE_INVALID_STEP_ID = "INVALID_STEP_ID"
STATE_DUPLICATE_STEP_ID = "DUPLICATE_STEP_ID"
STATE_UNSUPPORTED = "UNSUPPORTED_STEP_STATE"
STATE_INVALID_FLAG = "INVALID_EXECUTION_FLAG"
STATE_EXECUTED_PENDING = "EXECUTED_STEP_PENDING"
STATE_EXECUTION_NOT_OCCURRED = "EXECUTION_IMPLIED_WITHOUT_EXECUTION"
STATE_UNAUTHORIZED_EXECUTION = "EXECUTION_WITHOUT_AUTHORIZATION"
STATE_EXECUTED_NO_PROGRESS = "PLAN_EXECUTED_WITHOUT_STEP_PROGRESS"


class StepStateValidationResult:
    __slots__ = ("valid", "issues", "states")

    def __init__(self):
        self.valid = False
        self.issues = []
        self.states = {}     # step id -> state as declared (only for well-formed, unique ids)

    def codes(self):
        return [i["code"] for i in self.issues]

    def has(self, code):
        return code in self.codes()

    def to_dict(self):
        return {"valid": self.valid, "issues": [dict(i) for i in self.issues], "states": dict(self.states)}


def validate_plan_step_states(plan):
    """Pure, read-only consistency check of a `Plan`'s step states and execution flags. Issue order: flags,
    then steps in plan order, then plan-level combinations. Never raises, never mutates, never repairs."""
    res = StepStateValidationResult()
    if not isinstance(plan, Plan):
        res.issues.append(_failure(STATE_INVALID_PLAN, "Not a Plan; nothing to validate."))
        return res

    metadata = plan.metadata if isinstance(plan.metadata, dict) else {}
    flags = {}
    for name in ("executed", "execution_authorized"):
        value = metadata.get(name, None)
        if type(value) is not bool:
            res.issues.append(_failure(STATE_INVALID_FLAG, f"metadata[{name!r}] must be an explicit boolean.",
                                       flag=name))
        else:
            flags[name] = value
    executed, authorized = flags.get("executed"), flags.get("execution_authorized")

    seen, progressed = set(), False
    for idx, step in enumerate(plan.steps if isinstance(plan.steps, list) else []):
        sid = getattr(step, "step_id", None)
        if not isinstance(sid, str) or not sid.strip():
            res.issues.append(_failure(STATE_INVALID_STEP_ID, "A step has an empty or non-string id.", index=idx))
            continue
        if sid in seen:
            res.issues.append(_failure(STATE_DUPLICATE_STEP_ID, f"Duplicate step id: {sid}.", step_id=sid))
            continue
        seen.add(sid)
        state = getattr(step, "status", None)
        res.states[sid] = state
        if not isinstance(state, str) or state not in STEP_STATES:
            res.issues.append(_failure(STATE_UNSUPPORTED, f"Step {sid} has unsupported state {state!r}.",
                                       step_id=sid, state=state if isinstance(state, str) else None))
            continue
        has_output = getattr(step, "output_data", None) is not None
        if state in EXECUTION_STATES:
            progressed = True
        if state == STATUS_PENDING and has_output:
            res.issues.append(_failure(STATE_EXECUTED_PENDING,
                                       f"Step {sid} has recorded output but is still pending.", step_id=sid))
        if (state in EXECUTION_STATES or has_output) and executed is False:
            res.issues.append(_failure(STATE_EXECUTION_NOT_OCCURRED,
                                       f"Step {sid} implies execution but the plan is not executed.",
                                       step_id=sid))
        if (state in EXECUTION_STATES or has_output) and authorized is False:
            res.issues.append(_failure(STATE_UNAUTHORIZED_EXECUTION,
                                       f"Step {sid} implies execution but execution is not authorized.",
                                       step_id=sid))

    plan_state = plan.status
    if plan_state not in ALL_STATUSES:
        res.issues.append(_failure(STATE_UNSUPPORTED, f"The plan has unsupported state {plan_state!r}.",
                                   state=plan_state if isinstance(plan_state, str) else None))
    elif plan_state in EXECUTION_STATES and executed is False:
        res.issues.append(_failure(STATE_EXECUTION_NOT_OCCURRED,
                                   f"The plan state {plan_state!r} implies execution but the plan is not executed."))
    if executed is True:
        if authorized is False:
            res.issues.append(_failure(STATE_UNAUTHORIZED_EXECUTION,
                                       "The plan is marked executed without execution authorization."))
        if not progressed:
            res.issues.append(_failure(STATE_EXECUTED_NO_PROGRESS,
                                       "The plan is marked executed but no step has left the pending state."))
    res.valid = not res.issues
    return res


# --- plan step readiness (Prompt 686) --------------------------------------------------------------------
STATUS_READINESS_OK = "ok"

READY_INVALID_PLAN = "INVALID_PLAN_OBJECT"
READY_INVALID_FLAG = "INVALID_EXECUTION_FLAG"
READY_UNSUPPORTED_STATE = "UNSUPPORTED_STEP_STATE"


class PlanReadinessResult:
    __slots__ = ("status", "ready_step_ids", "steps", "dependency_validation", "failures", "executed",
                 "execution_authorized")

    def __init__(self):
        self.status = STATUS_REJECTED
        self.ready_step_ids = []
        self.steps = []              # fresh PlanStep copies in plan order (never the originals)
        self.dependency_validation = None
        self.failures = []
        self.executed = False        # this query never executes or authorizes anything
        self.execution_authorized = False

    @property
    def ok(self):
        return self.status == STATUS_READINESS_OK

    def codes(self):
        return [f["code"] for f in self.failures]

    def to_dict(self):
        return {
            "status": self.status,
            "ready_step_ids": list(self.ready_step_ids),
            "steps": [s.to_dict() for s in self.steps],
            "dependency_validation": (None if self.dependency_validation is None
                                      else self.dependency_validation.to_dict()),
            "failures": [dict(f) for f in self.failures],
            "executed": self.executed,
            "execution_authorized": self.execution_authorized,
        }


def get_ready_plan_steps(plan):
    """Steps of `plan` that are ready now (see module docstring, READINESS). Returns a `PlanReadinessResult`;
    `ok` with possibly-empty `ready_step_ids`, or rejected with failures. Never raises, never mutates."""
    result = PlanReadinessResult()
    if not isinstance(plan, Plan):
        result.failures = [_failure(READY_INVALID_PLAN, "Not a Plan; nothing to evaluate.")]
        return result
    steps = plan.steps
    check = validate_step_dependencies(plan)
    result.dependency_validation = check
    if not check.valid:
        result.failures = [_failure(FAIL_DEPENDENCY_GRAPH, "The step dependencies are invalid; readiness not "
                                    "determined.", issues=[dict(i) for i in check.issues])]
        return result

    metadata = plan.metadata if isinstance(plan.metadata, dict) else {}
    failures = []
    for name in ("executed", "execution_authorized"):
        if type(metadata.get(name, None)) is not bool:
            failures.append(_failure(READY_INVALID_FLAG, f"metadata[{name!r}] must be an explicit boolean.",
                                     flag=name))
    for step in steps:
        state = getattr(step, "status", None)
        if not isinstance(state, str) or state not in STEP_STATES:
            failures.append(_failure(READY_UNSUPPORTED_STATE,
                                     f"Step {step.step_id} has unsupported state {state!r}.",
                                     step_id=step.step_id, state=state if isinstance(state, str) else None))
    if failures:
        result.failures = failures
        return result

    states = {s.step_id: s.status for s in steps}
    result.status = STATUS_READINESS_OK
    # Authorization is permission to execute, not evidence of execution: it never changes readiness. Only step
    # state/output (below) says what has actually been executed.
    for step in steps:                        # plan order = deterministic order
        if step.status != STATUS_PENDING or step.output_data is not None:
            continue
        if all(states[dep] == STATUS_COMPLETED for dep in check.graph[step.step_id]):
            result.ready_step_ids.append(step.step_id)
            result.steps.append(_copy_step(step))
    return result


# --- plan progress evaluation (Prompt 687) ---------------------------------------------------------------
class PlanProgressResult:
    __slots__ = ("status", "total_steps", "pending_count", "in_progress_count", "completed_count", "failed_count",
                 "ready_step_ids", "blocked_step_ids", "is_complete", "is_blocked", "failures", "executed",
                 "execution_authorized")

    def __init__(self):
        self.status = STATUS_REJECTED
        self.total_steps = 0
        self.pending_count = 0
        self.in_progress_count = 0
        self.completed_count = 0
        self.failed_count = 0
        self.ready_step_ids = []
        self.blocked_step_ids = []   # pending steps behind a failed dependency, in plan order
        self.is_complete = False
        self.is_blocked = False
        self.failures = []
        self.executed = False        # this query never executes or authorizes anything
        self.execution_authorized = False

    @property
    def ok(self):
        return self.status == STATUS_READINESS_OK

    def codes(self):
        return [f["code"] for f in self.failures]

    def to_dict(self):
        return {
            "status": self.status,
            "total_steps": self.total_steps,
            "pending_count": self.pending_count,
            "in_progress_count": self.in_progress_count,
            "completed_count": self.completed_count,
            "failed_count": self.failed_count,
            "ready_step_ids": list(self.ready_step_ids),
            "blocked_step_ids": list(self.blocked_step_ids),
            "is_complete": self.is_complete,
            "is_blocked": self.is_blocked,
            "failures": [dict(f) for f in self.failures],
            "executed": self.executed,
            "execution_authorized": self.execution_authorized,
        }


def evaluate_plan_progress(plan):
    """Deterministic progress summary of `plan` (see module docstring, PROGRESS). Returns a
    `PlanProgressResult`; rejected (with the readiness failures) on invalid input. Never raises or mutates."""
    result = PlanProgressResult()
    readiness = get_ready_plan_steps(plan)
    if not readiness.ok:
        result.failures = [dict(f) for f in readiness.failures]
        return result

    graph = readiness.dependency_validation.graph
    steps = plan.steps
    states = {s.step_id: s.status for s in steps}
    counts = {state: 0 for state in STEP_STATES}
    for state in states.values():
        counts[state] += 1

    failed_reach, stuck, startable = {}, [], False
    for step in steps:                       # a valid graph only has earlier dependencies: one pass suffices
        sid = step.step_id
        behind_failed = any(failed_reach[dep] for dep in graph[sid])
        failed_reach[sid] = states[sid] == STATUS_FAILED or behind_failed
        if states[sid] == STATUS_PENDING:
            if behind_failed:
                stuck.append(sid)
            elif all(states[dep] == STATUS_COMPLETED for dep in graph[sid]):
                startable = True

    result.status = STATUS_READINESS_OK
    result.total_steps = len(steps)
    result.pending_count = counts[STATUS_PENDING]
    result.in_progress_count = counts[STATUS_IN_PROGRESS]
    result.completed_count = counts[STATUS_COMPLETED]
    result.failed_count = counts[STATUS_FAILED]
    result.ready_step_ids = list(readiness.ready_step_ids)
    result.blocked_step_ids = stuck
    result.is_complete = bool(steps) and counts[STATUS_COMPLETED] == len(steps)
    result.is_blocked = bool(stuck) and not result.ready_step_ids and not startable and not counts[STATUS_IN_PROGRESS]
    return result


def _digest(ctx):
    return hashlib.sha256(f"{ctx.normalized_request}\n{ctx.intent}".encode("utf-8")).hexdigest()[:12]


def _build_steps(ctx):
    """(steps, warnings) for a usable context. Dependencies are declared only where a step truly needs an
    earlier step's output; steps that do not need each other stay independent."""
    steps = []

    def add(description, expected_output, dependencies, input_data):
        step = PlanStep(f"step-{len(steps) + 1:03d}", description, dependencies=dependencies,
                        expected_output=expected_output, status=STATUS_PENDING, input_data=input_data)
        steps.append(step)
        return step.step_id

    first = add(f"Confirm the request and its intent ({ctx.intent}).", "confirmed_request", [],
                {"original_input": ctx.original_input, "normalized_request": ctx.normalized_request,
                 "intent": ctx.intent})
    for record in ctx.knowledge_context.get("current", []):
        name = record.get("name")
        add(f"Review current knowledge about {name}.", "knowledge_reviewed", [first],
            {"name": name, "term": record.get("term")})
    warnings = []
    for gap in ctx.information_gaps:
        if gap.get("blocking"):
            continue
        data = {"code": gap.get("code")}
        if isinstance(gap.get("term"), str):
            data["term"] = gap["term"]
        add(f"Address information gap {gap.get('code')}: {gap.get('message')}", "gap_addressed",
            [first], data)
        warnings.append(f"{gap.get('code')}: {gap.get('message')}")
    add("Prepare the response for the request.", "response_prepared", [s.step_id for s in steps], None)
    return steps, warnings


def build_plan_from_context(ctx):
    """Return a PlanBuildResult for `ctx` (see module docstring). Never raises for any input, never
    executes anything, never mutates `ctx`."""
    result = PlanBuildResult()
    failures = _context_failures(ctx)
    if failures:
        return _reject(result, failures)

    digest = _digest(ctx)
    goal_text = ctx.goal if isinstance(ctx.goal, str) and ctx.goal.strip() else ctx.normalized_request
    steps, warnings = _build_steps(ctx)

    dep_check = validate_step_dependencies(steps)
    if not dep_check.valid:
        _reject(result, [_failure(FAIL_DEPENDENCY_GRAPH, "The generated step dependencies are invalid.",
                                  issues=[dict(i) for i in dep_check.issues])])
        result.dependency_validation = dep_check
        return result

    plan = Plan(
        f"plan-{digest}", f"request-{digest}", steps=steps,
        expected_outputs=["response_prepared"], status=STATUS_PENDING, warnings=warnings,
        created_at=PLAN_CREATED_AT,
        metadata={
            "phase": "planning", "planner": PLANNER_NAME, "executed": False,
            "execution_authorized": False, "original_input": ctx.original_input,
            "normalized_request": ctx.normalized_request, "intent": ctx.intent, "goal": goal_text,
        },
    )
    validation = validate_plan(plan, goal=goal_text)
    if not validation.valid:
        return _reject(result, [_failure(FAIL_PLAN_INVALID, "The generated plan failed validation.",
                                         issues=validation.codes())])
    result.status = STATUS_PLANNED
    result.plan = plan
    result.validation = validation
    result.dependency_validation = dep_check
    return result
