"""
Self-Upgrade - Persistent Execution Context (Prompt 382)
==========================================================
`SelfUpgradeExecutionContext` is a small, persistent record of *where a
single self-upgrade request currently stands* across the controlled,
multi-step Self-Upgrade lifecycle - so `SelfUpgradeLifecycleCoordinator`
(self_upgrade.self_upgrade_lifecycle_coordinator, Prompt 381) can be
asked "what's next?" again after a restart without re-deriving the
whole chain from scratch, and without ever going backwards or claiming
progress that never actually happened.

    SelfUpgradeRequest.request_id                (Prompt 357)
        -> build_execution_context(...)          (this module)
        -> SelfUpgradeExecutionContext{...}
        -> SelfUpgradeExecutionContextStore.save/load  (this module,
           `memory.memory_system.MemorySystem.set_state`/`get_state`)
        -> SelfUpgradeLifecycleCoordinator.advance(context, ...)
           / .resume(context)                    (coordinator, extended
           in this same prompt)

THIS MODULE ONLY RECORDS PROGRESS. It never runs a stage, never builds
or generates anything, never approves or rejects anything, never
registers or verifies anything in the live Capability Registry, and
never activates or executes a capability (or any generated code) -
exactly the same boundary `self_upgrade_lifecycle_coordinator` already
draws for itself (see that module's docstring). Persisting a context is
bookkeeping, nothing more.

Reuses, never duplicates:
  - `self_upgrade.self_upgrade_lifecycle_coordinator.
    build_self_upgrade_lifecycle_decision` (Prompt 381, unchanged) is
    the *only* place a next lifecycle action is derived. This module
    never re-implements that decision table; it only records the
    `SelfUpgradeLifecycleDecision` dict that function already produced.
  - `memory.memory_system.MemorySystem.set_state`/`get_state` - the
    project's existing generic key-value persistence (already reused by
    `self_upgrade.capability_approval_manager.ApprovalManager` for
    exactly this reason) - is reused for storage here too, keyed
    `self_upgrade_execution_context:<upgrade_request_id>`. No new
    table, no new migration, no second database.
  - `self_upgrade.capability_registration_preparation._non_blank`
    (unchanged) is reused for the same "is this a real, non-blank
    value" check every other Self-Upgrade module already uses.
  - Every reference field below (`build_spec_reference`,
    `implementation_spec_reference`, `version_reference`,
    `approval_request_id`, `registration_plan_reference`,
    `registration_result_reference`, `verification_result_reference`)
    stores the *actual* already-produced object (or its id, where one
    exists) from the stage that produced it - a `CapabilityBuildSpec`,
    a `CapabilityImplementationSpec`, a `CapabilityLifecycleState`'s own
    `source_version`/`registration_plan`/`registration_result`/
    `verification_result`/`approval_request_id` - never a second,
    independently-derived copy of that data.

FIELDS (`SelfUpgradeExecutionContext`, exactly these keys):
    upgrade_request_id            - the `SelfUpgradeRequest.request_id`
                                     this context tracks. Required,
                                     never blank, never changes after
                                     creation.
    capability_name               - the capability this upgrade is
                                     building/registering, once known.
    current_lifecycle_state       - the full `CapabilityLifecycleState`
                                     dict (Prompt 379) this context was
                                     last updated from, or `None` before
                                     a build_result exists yet.
    current_action                - the `decision` label (one of
                                     `ALL_COORDINATOR_DECISIONS`) that
                                     is next, as of the last successful
                                     transition.
    last_completed_action         - the `decision` label that was
                                     `current_action` immediately before
                                     the last successful transition
                                     (i.e. the action that just
                                     finished) - `None` until at least
                                     one transition has happened.
    build_spec_reference          - the `CapabilityBuildSpec` dict, once
                                     the BUILD stage has one.
    implementation_spec_reference - the `CapabilityImplementationSpec`
                                     dict, once the ANALYZE/BUILD stage
                                     has one.
    version_reference             - the lifecycle state's own
                                     `source_version` (the compact
                                     version/snapshot reference Prompt
                                     379 already carries), once a
                                     version snapshot exists.
    approval_request_id           - the lifecycle state's own
                                     `approval_request_id`, once one
                                     exists.
    registration_plan_reference   - the lifecycle state's own
                                     `registration_plan`, once one
                                     exists.
    registration_result_reference - the lifecycle state's own
                                     `registration_result`, once one
                                     exists.
    verification_result_reference - the lifecycle state's own
                                     `verification_result`, once one
                                     exists.
    last_error                    - a short, human-readable string
                                     describing the most recent failed
                                     transition, or `None` immediately
                                     after any successful transition
                                     (a fresh success always clears a
                                     stale error).
    created_at / updated_at       - ISO-8601 UTC timestamps.

CONTEXT RULES (enforced here, matching the prompt this module was built
from):
  1. `build_execution_context` always returns a valid, fully-populated
     initial context (every reference field `None`, `current_action`
     and `last_completed_action` both `None`) for any non-blank
     `upgrade_request_id` - never a partial or malformed record.
  2. `apply_successful_transition` is the *only* way `current_action`,
     `current_lifecycle_state`, or `last_completed_action` ever
     advance, and it only does so when handed a `decision` whose own
     `decision` label is not `DECISION_INVALID` (i.e. the coordinator
     itself was actually able to determine a next step from the
     inputs it was given).
  3. A `decision` whose label *is* `DECISION_INVALID` is treated as a
     failed transition attempt: `apply_successful_transition` routes it
     straight to the same handling `apply_failed_transition` gives an
     explicit failure - the previous `current_action`,
     `current_lifecycle_state`, and every reference field are carried
     over completely unchanged, and only `last_error`/`updated_at`
     move.
  4. A rejected or blocked approval reaches this module as an ordinary
     lifecycle decision (`DECISION_BLOCKED`) - a real, valid decision,
     not a coordinator failure - so it *is* recorded as the new
     `current_action`/`current_lifecycle_state` via rule 2, exactly
     like any other legitimate lifecycle status. It is never silently
     dropped or downgraded back to whatever came before.
  5. `registration_plan_reference` / `registration_result_reference` /
     `verification_result_reference` / `version_reference` /
     `approval_request_id` are only ever overwritten with a *new*,
     non-`None` value read straight off the freshly-supplied
     `lifecycle_state` - an absent value on a given call never erases
     one already on record (register/verify/version/approve are each
     one-way stage transitions upstream; this module does not need a
     second way to "forget" one).
  6. Nothing in this module can move `current_action` to a state more
     advanced than the `lifecycle_state` actually supplied - every
     field written here is copied straight from that already-derived,
     already-validated `SelfUpgradeLifecycleDecision`, never guessed,
     interpolated, or advanced speculatively ahead of it.
  7. `LIFECYCLE_VERIFIED` / `DECISION_COMPLETED` are stored exactly as
     the coordinator reported them - "COMPLETED" - never rewritten to
     an "ACTIVE"-sounding action; there is no such action anywhere in
     `ALL_COORDINATOR_DECISIONS.` and nothing here invents one.
  8. Persisting, loading, or updating a context never calls the
     coordinator, an `ApprovalManager`, a `CapabilitySystem`, a
     `CapabilityHandlerRegistry`, or anything else that could execute,
     activate, approve, reject, or register a capability - this module
     only reads and writes plain dicts through
     `SelfUpgradeExecutionContextStore`.

Never raises: a malformed `upgrade_request_id`, `context`, or
`decision` is reported through a returned/unchanged value (see each
function's own docstring), never as an exception.
"""

import copy
from datetime import datetime, timezone

from self_upgrade.capability_registration_preparation import _non_blank
from self_upgrade.self_upgrade_lifecycle_coordinator import (
    DECISION_INVALID,
    ALL_COORDINATOR_DECISIONS,
    DECISION_ANALYZE,
    DECISION_BUILD,
    DECISION_BLOCKED,
    DECISION_FAILED,
    DECISION_COMPLETED,
)

_STATE_KEY_PREFIX = "self_upgrade_execution_context:"

# The only decisions a context may carry as `current_action`/
# `last_completed_action` while `current_lifecycle_state` is still
# `None` (Prompt 383's consistency check) - exactly the pre-pipeline
# branch `self_upgrade_lifecycle_coordinator._decide` takes when no
# `build_result` exists yet (ANALYZE/BUILD), plus the handful of
# outcomes a bare `SelfUpgradeRequest`/`CapabilityCreationPlan` can
# already report on its own (BLOCKED/INVALID/FAILED/COMPLETED) without
# ever reaching `build_capability_lifecycle_state`. Imported, not
# redefined: this is the same fixed set that module already produces
# for that branch, never a second decision table.
_PRE_PIPELINE_ACTIONS = frozenset(
    (DECISION_ANALYZE, DECISION_BUILD, DECISION_BLOCKED, DECISION_INVALID,
     DECISION_FAILED, DECISION_COMPLETED))

CONTEXT_FIELDS = (
    "upgrade_request_id",
    "capability_name",
    "current_lifecycle_state",
    "current_action",
    "last_completed_action",
    "build_spec_reference",
    "implementation_spec_reference",
    "version_reference",
    "approval_request_id",
    "registration_plan_reference",
    "registration_result_reference",
    "verification_result_reference",
    "last_error",
    "created_at",
    "updated_at",
)


def _now():
    return datetime.now(timezone.utc).isoformat()


def _state_key(upgrade_request_id):
    return f"{_STATE_KEY_PREFIX}{upgrade_request_id}"


# ----------------------------------------------------------------------
# Building / updating (pure, side-effect free - see module docstring)
# ----------------------------------------------------------------------
def build_execution_context(upgrade_request_id, capability_name=None):
    """A new, valid initial `SelfUpgradeExecutionContext` for
    `upgrade_request_id` (context rule 1). Every reference field starts
    `None`; `current_action` and `last_completed_action` both start
    `None` too, since no lifecycle decision has been recorded yet.

    Returns `None` - never raises, never a partial dict - if
    `upgrade_request_id` is not a non-blank string.
    """
    if not _non_blank(upgrade_request_id):
        return None

    now = _now()
    return {
        "upgrade_request_id": upgrade_request_id,
        "capability_name": capability_name,
        "current_lifecycle_state": None,
        "current_action": None,
        "last_completed_action": None,
        "build_spec_reference": None,
        "implementation_spec_reference": None,
        "version_reference": None,
        "approval_request_id": None,
        "registration_plan_reference": None,
        "registration_result_reference": None,
        "verification_result_reference": None,
        "last_error": None,
        "created_at": now,
        "updated_at": now,
    }


def _is_context(context):
    return isinstance(context, dict) and _non_blank(context.get("upgrade_request_id"))


def validate_execution_context(context):
    """A list of consistency problems with `context` (empty if it is
    internally consistent) - the read-only check
    `self_upgrade_resume_manager.SelfUpgradeResumeManager` runs before
    ever resuming from a persisted context (Prompt 383's CONSISTENCY
    VALIDATION requirement). Never repairs anything - a caller decides
    what to do with a non-empty list (e.g. report `INVALID_CONTEXT`
    rather than resume). Never raises.

    Checks, in order:
      - `context` has every `CONTEXT_FIELDS` key and a non-blank
        `upgrade_request_id` ("upgrade request ID exists").
      - `current_action`/`last_completed_action`, when set, are each
        one of `ALL_COORDINATOR_DECISIONS` - and, while
        `current_lifecycle_state` is still `None`, one of the fixed
        pre-pipeline outcomes that branch can actually report
        ("lifecycle state matches available results").
      - when `current_lifecycle_state` is present: its own
        `capability_name` agrees with `context["capability_name"]`
        ("capability name matches the context"), and its own
        `approval_request_id`/`registration_plan`/`registration_result`/
        `verification_result`/`source_version` - wherever it carries a
        non-blank one - agree with the matching context reference field
        ("approval references are consistent", "version/snapshot
        references are consistent", "registration references are
        consistent", "verification references are consistent").
    """
    errors = []

    if not isinstance(context, dict):
        return ["context must be a SelfUpgradeExecutionContext dict."]

    missing_fields = [f for f in CONTEXT_FIELDS if f not in context]
    if missing_fields:
        errors.append(f"context is missing required field(s): {missing_fields}.")

    if not _non_blank(context.get("upgrade_request_id")):
        errors.append("context is missing a non-blank upgrade_request_id.")

    current_action = context.get("current_action")
    last_completed_action = context.get("last_completed_action")
    lifecycle_state = context.get("current_lifecycle_state")

    for label, action in (("current_action", current_action),
                           ("last_completed_action", last_completed_action)):
        if action is None:
            continue
        if action not in ALL_COORDINATOR_DECISIONS:
            errors.append(f"context.{label}={action!r} is not a recognized decision.")
        elif lifecycle_state is None and action not in _PRE_PIPELINE_ACTIONS:
            errors.append(
                f"context.{label}={action!r} implies a lifecycle result that "
                "current_lifecycle_state does not carry.")

    if lifecycle_state is not None:
        if not isinstance(lifecycle_state, dict):
            errors.append("context.current_lifecycle_state must be a dict when set.")
        else:
            state_name = lifecycle_state.get("capability_name")
            context_name = context.get("capability_name")
            if _non_blank(state_name) and _non_blank(context_name) and state_name != context_name:
                errors.append(
                    f"context.capability_name={context_name!r} does not match "
                    f"current_lifecycle_state.capability_name={state_name!r}.")

            reference_checks = (
                ("approval_request_id", "approval_request_id"),
                ("registration_plan", "registration_plan_reference"),
                ("registration_result", "registration_result_reference"),
                ("verification_result", "verification_result_reference"),
                ("source_version", "version_reference"),
            )
            for state_key, context_key in reference_checks:
                state_value = lifecycle_state.get(state_key)
                blank = state_value is None or (
                    isinstance(state_value, str) and not state_value.strip())
                if blank:
                    continue
                if context.get(context_key) != state_value:
                    errors.append(
                        f"context.{context_key} does not match "
                        f"current_lifecycle_state.{state_key}.")

    return errors


def apply_failed_transition(context, error, decision=None):
    """Record a failed transition attempt (context rule 3): every field
    describing the *previous successful state* -
    (`current_action`, `current_lifecycle_state`, `last_completed_action`,
    and every `*_reference`/`approval_request_id` field) is carried over
    completely unchanged from `context`. Only `last_error` (a short,
    human-readable string) and `updated_at` change.

    `decision` may optionally be the `SelfUpgradeLifecycleDecision` that
    triggered this failure (e.g. one whose `decision` is
    `DECISION_INVALID`), purely so a caller-supplied `error` can be
    filled in from its `reason`/`errors` when not given explicitly -
    it is never itself stored, and none of its fields are copied into
    the returned context.

    Returns a new dict (never mutates `context`); returns `context`
    itself, unchanged, if `context` is not a valid execution context.
    Never raises.
    """
    if not _is_context(context):
        return context

    if not _non_blank(error) and isinstance(decision, dict):
        error = decision.get("reason") or "; ".join(
            str(e) for e in (decision.get("errors") or []) if e
        ) or None

    new_context = copy.deepcopy(context)
    new_context["last_error"] = error if _non_blank(error) else "Lifecycle transition failed."
    new_context["updated_at"] = _now()
    return new_context


def apply_successful_transition(context, decision, build_spec=None, implementation_spec=None):
    """Record a successful lifecycle transition (context rule 2): given
    the existing `context` and a freshly-computed
    `SelfUpgradeLifecycleDecision` (from
    `self_upgrade_lifecycle_coordinator.build_self_upgrade_lifecycle_decision`
    / `SelfUpgradeLifecycleCoordinator.decide`), returns a new context
    with:
      - `last_completed_action` set to the *previous* `current_action`
        (the action that just finished),
      - `current_action` set to `decision["decision"]`,
      - `current_lifecycle_state` set to `decision["lifecycle_state"]`,
      - `capability_name` refreshed from `decision["capability_name"]`
        when present,
      - every reference field (`approval_request_id`,
        `registration_plan_reference`, `registration_result_reference`,
        `verification_result_reference`, `version_reference`) refreshed
        from the supplied `lifecycle_state`, but only where it actually
        carries a non-blank value (context rule 5),
      - `last_error` cleared back to `None`,
      - `updated_at` bumped.

    `build_spec`/`implementation_spec`, when supplied, are stored as
    `build_spec_reference`/`implementation_spec_reference` verbatim -
    this is the one place those two references ever get attached, since
    neither is part of a `CapabilityLifecycleState` itself.

    If `decision["decision"] == DECISION_INVALID` - the coordinator
    itself could not determine a next step - this is routed to
    `apply_failed_transition` instead (context rule 3), and
    `build_spec`/`implementation_spec` are ignored, so a coordinator
    failure can never smuggle a reference update past that rule.

    Returns a new dict (never mutates `context`); returns `context`
    itself, unchanged, if `context` is not a valid execution context or
    `decision` is not a dict. Never raises.
    """
    if not _is_context(context):
        return context
    if not isinstance(decision, dict):
        return context

    if decision.get("decision") == DECISION_INVALID:
        return apply_failed_transition(context, None, decision=decision)

    new_context = copy.deepcopy(context)

    if _non_blank(decision.get("capability_name")):
        new_context["capability_name"] = decision.get("capability_name")

    new_context["last_completed_action"] = context.get("current_action")
    new_context["current_action"] = decision.get("decision")
    new_context["current_lifecycle_state"] = decision.get("lifecycle_state")
    new_context["last_error"] = None

    lifecycle_state = decision.get("lifecycle_state")
    if isinstance(lifecycle_state, dict):
        if _non_blank(lifecycle_state.get("approval_request_id")):
            new_context["approval_request_id"] = lifecycle_state.get("approval_request_id")
        if lifecycle_state.get("registration_plan") is not None:
            new_context["registration_plan_reference"] = lifecycle_state.get("registration_plan")
        if lifecycle_state.get("registration_result") is not None:
            new_context["registration_result_reference"] = \
                lifecycle_state.get("registration_result")
        if lifecycle_state.get("verification_result") is not None:
            new_context["verification_result_reference"] = \
                lifecycle_state.get("verification_result")
        if lifecycle_state.get("source_version") is not None:
            new_context["version_reference"] = lifecycle_state.get("source_version")

    if build_spec is not None:
        new_context["build_spec_reference"] = build_spec
    if implementation_spec is not None:
        new_context["implementation_spec_reference"] = implementation_spec

    new_context["updated_at"] = _now()
    return new_context


# ----------------------------------------------------------------------
# Persistence - the project's existing generic key-value state table,
# never a second storage system (matches
# self_upgrade.capability_approval_manager.ApprovalManager exactly).
# ----------------------------------------------------------------------
class SelfUpgradeExecutionContextStore:
    """Stores/retrieves `SelfUpgradeExecutionContext` dicts, one per
    `upgrade_request_id`, through the project's existing
    `MemorySystem.set_state`/`get_state` key-value table. Holds no
    in-memory state of its own beyond the `memory` reference it was
    constructed with, so a context saved before a restart is read back
    unchanged afterwards as long as the same (or an equivalent,
    same-file) `MemorySystem` is used - the project's existing
    persistence guarantee, not a new one.

    Read-only with respect to the lifecycle itself: nothing here calls
    the coordinator, an `ApprovalManager`, or a `CapabilitySystem`."""

    def __init__(self, memory):
        self.memory = memory

    def save(self, context):
        """Persist `context` under its own `upgrade_request_id`.
        Returns `context` unchanged on success, or `None` - and stores
        nothing - if `context` is not a valid execution context. Never
        raises."""
        if not _is_context(context):
            return None
        self.memory.set_state(_state_key(context["upgrade_request_id"]), context)
        return context

    def load(self, upgrade_request_id):
        """The stored `SelfUpgradeExecutionContext` for
        `upgrade_request_id`, or `None` if none exists (never raises
        for a blank/unknown id - same "safe on a miss" convention
        `ApprovalManager.get_request`/`get`-style lookups already use
        across this project)."""
        if not _non_blank(upgrade_request_id):
            return None
        return self.memory.get_state(_state_key(upgrade_request_id))

    def get_or_create(self, upgrade_request_id, capability_name=None):
        """The stored context for `upgrade_request_id` if one already
        exists (loaded, never recreated or overwritten - matches
        `ApprovalManager.create_request`'s own "never clobber an
        existing record" rule), otherwise a freshly-built initial
        context (context rule 1) that is saved and returned. Returns
        `None` - and saves nothing - for a blank `upgrade_request_id`."""
        existing = self.load(upgrade_request_id)
        if existing is not None:
            return existing
        context = build_execution_context(upgrade_request_id, capability_name=capability_name)
        return self.save(context)
