"""
Planning - Adaptive Plan Proposal
====================================
`AdaptivePlanProposal` answers the question directly downstream of
`AdaptivePlanAnalyzer` (planning/adaptive_plan_analyzer.py) - "given the
blockers that analyzer already found, is there a safe, well-evidenced
structural change to propose for this Plan, or should a human be told
why not?":

    GOAL + PLAN
        -> AdaptivePlanAnalyzer.analyze  (read-only: *why* isn't this
           Plan satisfying this Goal - a list of observed Blockers)
        -> AdaptivePlanProposal.propose  (read-only: *what*, if
           anything, could safely be changed about the Plan in
           response to those Blockers)
        -> a single, structured proposal - never applied, by this
           module or anything it calls, to the Plan it describes

This is a *proposal* generator, not a planning engine and not an
executor: it never modifies a Goal/Plan/PlanStep, never executes a
step or a capability, never retries anything, never creates or
installs a capability, and never touches the network or an external
AI API. Every `ProposedChange` it returns is a plain, inert
description of a change someone (a human, or a future, separate,
explicitly-invoked apply step) could choose to make - this module
itself makes nothing happen.

Just as `AdaptivePlanAnalyzer` refuses to invent a blocker that isn't
actually backed by recorded state, this module refuses to invent a
*fix* that isn't safely, deterministically derivable from a Blocker's
own already-computed evidence. Converting a Blocker into a
`ProposedChange` is a fixed, per-blocker-type lookup (see
`_propose_for_blocker` below) - never free-form reasoning, never a
call to an external model, never a random or "best guess" confidence
score. When a Blocker doesn't map to any safe, structural change (for
example `MISSING_CAPABILITY` - installing/enabling a capability is
explicitly outside what a Plan-structure change, or this module, is
allowed to do), this module adds a warning explaining that instead of
guessing at a fix - the same "no evidence, no invented answer"
convention `AdaptivePlanAnalyzer`/`GoalCompletionEvaluator` already
apply to blockers and Goal-satisfaction state respectively.
"""

import itertools
from datetime import datetime, timezone

from .goal_manager import GoalManager
from .plan_manager import PlanManager
from .plan import ensure_structured_data, STATUS_COMPLETED
from .goal_completion import STATE_SATISFIED
from .adaptive_plan_analyzer import (
    AdaptivePlanAnalyzer,
    ANALYSIS_UNKNOWN,
    BLOCKER_MISSING_STEP,
    BLOCKER_FAILED_STEP,
    BLOCKER_BLOCKED_STEP,
    BLOCKER_MISSING_CAPABILITY,
    BLOCKER_UNAVAILABLE_CAPABILITY,
    BLOCKER_MISSING_HANDLER,
    BLOCKER_UNRESOLVED_DEPENDENCY,
    BLOCKER_MISSING_INPUT,
    BLOCKER_MISSING_OUTPUT,
    BLOCKER_EXECUTION_FAILURE,
    BLOCKER_GOAL_NOT_SATISFIED,
)


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


# ----------------------------------------------------------------------
# Controlled vocabularies (requirements 7, 8)
# ----------------------------------------------------------------------
PROPOSAL_NO_CHANGE_NEEDED = "NO_CHANGE_NEEDED"
PROPOSAL_CHANGE_RECOMMENDED = "CHANGE_RECOMMENDED"
PROPOSAL_BLOCKED = "BLOCKED"
PROPOSAL_UNKNOWN = "UNKNOWN"

ALL_PROPOSAL_STATUSES = (
    PROPOSAL_NO_CHANGE_NEEDED, PROPOSAL_CHANGE_RECOMMENDED,
    PROPOSAL_BLOCKED, PROPOSAL_UNKNOWN,
)

CHANGE_ADD_STEP = "ADD_STEP"
CHANGE_MODIFY_STEP = "MODIFY_STEP"
CHANGE_REMOVE_STEP = "REMOVE_STEP"
CHANGE_ADD_DEPENDENCY = "ADD_DEPENDENCY"
CHANGE_REMOVE_DEPENDENCY = "REMOVE_DEPENDENCY"
CHANGE_ADD_CAPABILITY_REQUIREMENT = "ADD_CAPABILITY_REQUIREMENT"
CHANGE_REMOVE_CAPABILITY_REQUIREMENT = "REMOVE_CAPABILITY_REQUIREMENT"
CHANGE_PROVIDE_INPUT = "PROVIDE_INPUT"
CHANGE_PROVIDE_OUTPUT = "PROVIDE_OUTPUT"
CHANGE_REORDER_STEP = "REORDER_STEP"

ALL_CHANGE_TYPES = (
    CHANGE_ADD_STEP, CHANGE_MODIFY_STEP, CHANGE_REMOVE_STEP,
    CHANGE_ADD_DEPENDENCY, CHANGE_REMOVE_DEPENDENCY,
    CHANGE_ADD_CAPABILITY_REQUIREMENT, CHANGE_REMOVE_CAPABILITY_REQUIREMENT,
    CHANGE_PROVIDE_INPUT, CHANGE_PROVIDE_OUTPUT, CHANGE_REORDER_STEP,
)

# `validate_proposal`'s controlled check names (requirement 15) - same
# "each failure names exactly which check it is" convention
# execution/preflight.py's own CHECK_* constants already use.
CHECK_STRUCTURE = "structure"
CHECK_STATUS_VALID = "status_valid"
CHECK_CHANGE_TYPE_VALID = "change_type_valid"
CHECK_TARGET_STEP_VALID = "target_step_valid"
CHECK_PROPOSED_DATA_SAFE = "proposed_data_safe"
CHECK_CONFIDENCE_VALID = "confidence_valid"

_REQUIRED_PROPOSAL_KEYS = (
    "proposal_id", "goal_id", "plan_id", "status", "reason",
    "source_blockers", "proposed_changes", "affected_steps",
    "required_capabilities", "warnings", "created_at",
)
_REQUIRED_CHANGE_KEYS = (
    "change_id", "change_type", "target_step_id", "reason",
    "source_blocker", "proposed_data", "confidence",
)

_id_counter = itertools.count(1)


def _generate_proposal_id():
    return f"proposal-{next(_id_counter)}"


_change_id_counter = itertools.count(1)


def _generate_change_id():
    return f"change-{next(_change_id_counter)}"


class ProposedChange:
    """One structured, inert description of a single change someone
    could make to a Plan in response to one specific `Blocker`
    (planning/adaptive_plan_analyzer.py). Calling this into existence
    never changes anything - same "plain data record" convention as
    `Blocker` itself.

    `confidence` is a float in `[0.0, 1.0]`, always produced by a
    fixed rule keyed to the originating blocker type and the concrete
    structural facts already on record (e.g. "exactly one completed
    dependency" vs "several") - never a free-form or random guess
    (requirement 10)."""

    __slots__ = (
        "change_id", "change_type", "target_step_id", "reason",
        "source_blocker", "proposed_data", "confidence",
    )

    def __init__(
        self, change_type, target_step_id, reason, source_blocker,
        proposed_data=None, confidence=0.0, change_id=None,
    ):
        if change_type not in ALL_CHANGE_TYPES:
            raise ValueError(f"Unknown change_type: {change_type!r}")
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            raise TypeError("ProposedChange confidence must be a number.")
        if not (0.0 <= float(confidence) <= 1.0):
            raise ValueError("ProposedChange confidence must be between 0.0 and 1.0.")

        self.change_id = change_id if change_id is not None else _generate_change_id()
        self.change_type = change_type
        self.target_step_id = target_step_id
        self.reason = reason
        self.source_blocker = source_blocker
        # Routed through the exact same structural-safety check
        # PlanStep.set_input/set_output and ExecutionEvent already use
        # (planning/plan.py's ensure_structured_data) - never an
        # arbitrary object, always plain JSON-shaped data.
        self.proposed_data = ensure_structured_data(proposed_data) if proposed_data is not None else {}
        self.confidence = float(confidence)

    def __repr__(self):
        return (
            f"ProposedChange(change_id={self.change_id!r}, "
            f"change_type={self.change_type!r}, target_step_id={self.target_step_id!r}, "
            f"confidence={self.confidence!r})"
        )

    def to_dict(self):
        return {
            "change_id": self.change_id,
            "change_type": self.change_type,
            "target_step_id": self.target_step_id,
            "reason": self.reason,
            "source_blocker": self.source_blocker,
            "proposed_data": ensure_structured_data(self.proposed_data),
            "confidence": self.confidence,
        }


class PlanProposal:
    """One structured, inert proposal for a single (Goal, Plan) pair -
    a `status`, a human-readable `reason`, and zero or more
    `ProposedChange` records. Same "plain data record with a
    `to_dict()`" convention as `Blocker`/`Plan`/`Goal`. Building one of
    these never changes the Plan or Goal it describes."""

    __slots__ = (
        "proposal_id", "goal_id", "plan_id", "status", "reason",
        "source_blockers", "proposed_changes", "affected_steps",
        "required_capabilities", "warnings", "created_at",
    )

    def __init__(
        self, goal_id, plan_id, status, reason, source_blockers=None,
        proposed_changes=None, affected_steps=None, required_capabilities=None,
        warnings=None, proposal_id=None, created_at=None,
    ):
        if status not in ALL_PROPOSAL_STATUSES:
            raise ValueError(f"Unknown proposal status: {status!r}")
        for change in (proposed_changes or []):
            if not isinstance(change, ProposedChange):
                raise TypeError("PlanProposal.proposed_changes must contain ProposedChange instances.")

        self.proposal_id = proposal_id if proposal_id is not None else _generate_proposal_id()
        self.goal_id = goal_id
        self.plan_id = plan_id
        self.status = status
        self.reason = reason
        self.source_blockers = list(source_blockers) if source_blockers else []
        self.proposed_changes = list(proposed_changes) if proposed_changes else []
        self.affected_steps = list(affected_steps) if affected_steps else []
        self.required_capabilities = list(required_capabilities) if required_capabilities else []
        self.warnings = list(warnings) if warnings else []
        self.created_at = created_at if created_at is not None else _now_iso()

    def __repr__(self):
        return (
            f"PlanProposal(proposal_id={self.proposal_id!r}, goal_id={self.goal_id!r}, "
            f"plan_id={self.plan_id!r}, status={self.status!r}, "
            f"changes={len(self.proposed_changes)})"
        )

    def to_dict(self):
        return {
            "proposal_id": self.proposal_id,
            "goal_id": self.goal_id,
            "plan_id": self.plan_id,
            "status": self.status,
            "reason": self.reason,
            "source_blockers": list(self.source_blockers),
            "proposed_changes": [change.to_dict() for change in self.proposed_changes],
            "affected_steps": list(self.affected_steps),
            "required_capabilities": list(self.required_capabilities),
            "warnings": list(self.warnings),
            "created_at": self.created_at,
        }


class AdaptivePlanProposal:
    """Not thread-safe (matches `AdaptivePlanAnalyzer`/`AgentLoop`).
    Safe to use one instance per Core / per conversation session.

    `goal_manager` and `plan_manager` are required. `analyzer`, if
    given, must be an `AdaptivePlanAnalyzer`, and is reused exactly as
    provided - `propose` always calls straight into
    `analyzer.analyze`, never a second, disagreeing copy of blocker
    detection. When omitted, a new `AdaptivePlanAnalyzer` is built from
    `goal_manager`/`plan_manager` plus whichever of the optional
    capability/execution collaborators below were supplied - same
    "build a sensible default, but never guess at a missing required
    collaborator" convention `AgentLoop`/`AdaptivePlanAnalyzer`
    themselves already follow.

    `capability_system`, `capability_handlers`, `executable_capabilities`,
    `execution_history`, `event_log` are forwarded unchanged to the
    `AdaptivePlanAnalyzer` this builds when `analyzer` is omitted; they
    are unused (and irrelevant) when an `analyzer` is supplied directly.
    """

    def __init__(
        self,
        goal_manager,
        plan_manager,
        analyzer=None,
        capability_system=None,
        capability_handlers=None,
        executable_capabilities=None,
        execution_history=None,
        event_log=None,
    ):
        if not isinstance(goal_manager, GoalManager):
            raise TypeError("AdaptivePlanProposal requires a GoalManager instance.")
        if not isinstance(plan_manager, PlanManager):
            raise TypeError("AdaptivePlanProposal requires a PlanManager instance.")
        if analyzer is not None and not isinstance(analyzer, AdaptivePlanAnalyzer):
            raise TypeError("AdaptivePlanProposal's analyzer must be an AdaptivePlanAnalyzer instance.")

        self._goal_manager = goal_manager
        self._plan_manager = plan_manager
        self._analyzer = analyzer if analyzer is not None else AdaptivePlanAnalyzer(
            goal_manager, plan_manager,
            capability_system=capability_system,
            capability_handlers=capability_handlers,
            executable_capabilities=executable_capabilities,
            execution_history=execution_history,
            event_log=event_log,
        )

    # ------------------------------------------------------------------
    # Result shaping
    # ------------------------------------------------------------------
    def _unknown_proposal(self, goal_id, plan_id, message):
        proposal = PlanProposal(
            goal_id, plan_id, PROPOSAL_UNKNOWN, message, warnings=[message],
        )
        return proposal.to_dict()

    @staticmethod
    def _merge(target_list, source_list):
        for item in source_list:
            if item not in target_list:
                target_list.append(item)

    # ------------------------------------------------------------------
    # Blocker -> ProposedChange / warning (requirements 5, 8, 9, 10, 11, 12)
    # ------------------------------------------------------------------
    def _propose_for_blocker(
        self, blocker, blockers, steps_by_id, missing_step_deps_by_step,
        missing_output_by_step,
    ):
        """Returns `(change_or_none, warning_or_none)` for a single
        blocker dict (as produced by `AdaptivePlanAnalyzer.analyze`).
        Fixed, deterministic, per-blocker-type mapping only - see this
        module's own docstring and requirement 11's example mapping
        table. Never inspects anything beyond `blocker`'s own already-
        computed fields, the sibling `blockers` for the same step, and
        already-existing `PlanStep` structure (dependencies/status) -
        never invents a fact that isn't already on record."""
        btype = blocker["type"]
        step_id = blocker["step_id"]
        step = steps_by_id.get(step_id) if step_id is not None else None

        if btype == BLOCKER_FAILED_STEP:
            execution_failure = next(
                (b for b in blockers if b["type"] == BLOCKER_EXECUTION_FAILURE and b["step_id"] == step_id),
                None,
            )
            proposed_data = {"suggested_action": "review_and_retry"}
            if execution_failure is not None:
                proposed_data["error_evidence"] = list(execution_failure["evidence"])
                confidence = 0.7
            else:
                confidence = 0.3
            return ProposedChange(
                CHANGE_MODIFY_STEP, step_id,
                reason=f"Step {step_id!r} failed; review and correct it before it is retried.",
                source_blocker=blocker["blocker_id"], proposed_data=proposed_data,
                confidence=confidence,
            ), None

        if btype == BLOCKER_EXECUTION_FAILURE:
            # Folded into the sibling FAILED_STEP change above (its
            # evidence is attached there) - proposing a second,
            # separate MODIFY_STEP change from the same underlying
            # failure would be a duplicate, not a distinct finding.
            return None, None

        if btype == BLOCKER_MISSING_STEP:
            dep_ids = missing_step_deps_by_step.get(step_id, [])
            if not dep_ids:
                return None, f"{blocker['description']} No automatic plan change is proposed for this blocker."
            # One MISSING_STEP blocker is already per-dependency (see
            # AdaptivePlanAnalyzer), so there is exactly one dangling
            # dependency id to remove here.
            dep_id = dep_ids[0]
            return ProposedChange(
                CHANGE_REMOVE_DEPENDENCY, step_id,
                reason=(
                    f"Step {step_id!r} depends on {dep_id!r}, which does not exist in "
                    "this plan; removing the dangling dependency reference is a safe, "
                    "purely structural correction."
                ),
                source_blocker=blocker["blocker_id"],
                proposed_data={"remove_dependency": dep_id},
                confidence=1.0,
            ), None

        if btype == BLOCKER_UNRESOLVED_DEPENDENCY:
            return None, (
                f"{blocker['description']} No automatic plan change is proposed for "
                "this blocker; the dependency is valid and may still complete on its own."
            )

        if btype == BLOCKER_MISSING_INPUT:
            dependencies = list(step.dependencies) if step is not None else []
            completed_dep_ids = [
                dep_id for dep_id in dependencies
                if steps_by_id.get(dep_id) is not None and steps_by_id[dep_id].status == STATUS_COMPLETED
            ]
            if len(completed_dep_ids) == 1:
                confidence = 0.9
            elif completed_dep_ids:
                confidence = 0.6
            else:
                confidence = 0.3
            return ProposedChange(
                CHANGE_PROVIDE_INPUT, step_id,
                reason=(
                    f"Step {step_id!r} has completed dependencies but no recorded "
                    "input_data; propagate a completed dependency's output to it."
                ),
                source_blocker=blocker["blocker_id"],
                proposed_data={"candidate_source_steps": completed_dep_ids},
                confidence=confidence,
            ), None

        if btype == BLOCKER_MISSING_OUTPUT:
            expected_output = missing_output_by_step.get(step_id)
            return ProposedChange(
                CHANGE_PROVIDE_OUTPUT, step_id,
                reason=(
                    f"Step {step_id!r} is COMPLETED and declares expected_output "
                    f"{expected_output!r}, but has no recorded output_data."
                ),
                source_blocker=blocker["blocker_id"],
                proposed_data={"expected_output": expected_output},
                # A gap is certain (the step is COMPLETED with a
                # declared expected_output and no output_data); the
                # correct value is not observable from recorded state,
                # so confidence reflects "a fix is needed", not "this
                # is the fix" - moderate, never a guessed value.
                confidence=0.5,
            ), None

        if btype in (BLOCKER_MISSING_CAPABILITY, BLOCKER_UNAVAILABLE_CAPABILITY, BLOCKER_MISSING_HANDLER):
            # Registering/enabling a capability or wiring a handler is
            # explicitly outside what a Plan-structure change (or this
            # module) is allowed to do (requirement 13) - a warning is
            # the correct, honest output here, never an invented
            # ADD_CAPABILITY_REQUIREMENT/handler fix.
            return None, (
                f"{blocker['description']} No automatic plan change is proposed; "
                "capability registration and handler wiring happen outside the Plan "
                "and are not something this proposal system can perform or fix."
            )

        if btype == BLOCKER_BLOCKED_STEP:
            has_specific_sibling = any(
                b["step_id"] == step_id and b["type"] != BLOCKER_BLOCKED_STEP for b in blockers
            )
            if has_specific_sibling:
                # A more specific blocker for the same step (dependency/
                # capability/etc.) already produced its own change or
                # warning above - this summary blocker would only
                # duplicate it.
                return None, None
            return None, f"{blocker['description']} No automatic plan change is proposed for this blocker."

        if btype == BLOCKER_GOAL_NOT_SATISFIED:
            # requirement 11: "ADD_STEP only when observable evidence
            # supports it" - this blocker's own evidence is a Plan.status
            # discrepancy, not a description of what a missing step
            # should do, so there is nothing safe to propose here.
            return None, (
                f"{blocker['description']} There is not enough observable evidence to "
                "safely propose adding or modifying a step for this; manual review is "
                "recommended."
            )

        # Defensive fallback for any future blocker type this mapping
        # doesn't yet know about - never silently drop a blocker.
        return None, f"{blocker['description']} No automatic plan change is proposed for this blocker."

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def propose(self, goal_id, plan_id):
        """Propose zero or more safe, structural changes to Plan
        `plan_id` in response to Goal `goal_id` not (yet) being
        satisfied, using only `AdaptivePlanAnalyzer.analyze`'s own
        already-computed blockers.

        Performs the same three checks, in the same order, `analyze`
        itself performs (requirements 1-3), by delegating to it
        directly - never a second, disagreeing copy of goal/plan/
        ownership verification. When `analyze` itself can't determine
        anything (`analysis_status == UNKNOWN`), this returns a
        `PROPOSAL_UNKNOWN` proposal carrying the same warnings,
        rather than guessing at a proposal from no evidence.

        Read-only throughout (requirement 13): never modifies the
        Goal, Plan, or any PlanStep; never executes a step or a
        capability; never retries anything; never creates or installs
        a capability; never accesses the network or calls an external
        AI API.

        Returns the structured dict described by `PlanProposal.to_dict`
        (requirement 6)."""
        goal = self._goal_manager.get_goal(goal_id)
        if goal is None:
            return self._unknown_proposal(goal_id, plan_id, f"No Goal found for goal_id {goal_id!r}.")

        plan = self._plan_manager.get_plan(plan_id)
        if plan is None:
            return self._unknown_proposal(goal_id, plan_id, f"No Plan found for plan_id {plan_id!r}.")

        if plan.goal_id != goal_id:
            return self._unknown_proposal(
                goal_id, plan_id,
                f"Plan {plan_id!r} belongs to goal_id {plan.goal_id!r}, not the "
                f"requested goal_id {goal_id!r}; refusing to propose changes against "
                "a goal this plan isn't attached to.",
            )

        analysis = self._analyzer.analyze(goal_id, plan_id)
        if analysis["analysis_status"] == ANALYSIS_UNKNOWN:
            message = "; ".join(analysis["warnings"]) or "Underlying analysis could not be determined."
            return self._unknown_proposal(goal_id, plan_id, message)

        blockers = analysis["blockers"]
        warnings = list(analysis["warnings"])

        if not blockers:
            if analysis["goal_status"] == STATE_SATISFIED:
                reason = "Goal is already satisfied; no changes are needed."
            else:
                reason = "No blockers were observed; no changes are needed at this time."
            proposal = PlanProposal(
                goal_id, plan_id, PROPOSAL_NO_CHANGE_NEEDED, reason, warnings=warnings,
            )
            return proposal.to_dict()

        steps_by_id = {step.step_id: step for step in plan.steps}

        missing_step_deps_by_step = {}
        for entry in analysis["unresolved_dependencies"]:
            if entry["reason"] == "missing_step":
                missing_step_deps_by_step.setdefault(entry["step_id"], []).append(entry["dependency_id"])

        missing_output_by_step = {
            entry["step_id"]: entry["expected_output"] for entry in analysis["missing_outputs"]
        }

        changes = []
        source_blockers = []
        affected_steps = []

        for blocker in blockers:
            source_blockers.append(blocker["blocker_id"])
            if blocker["step_id"] is not None:
                self._merge(affected_steps, [blocker["step_id"]])

            change, warning = self._propose_for_blocker(
                blocker, blockers, steps_by_id, missing_step_deps_by_step, missing_output_by_step,
            )
            if change is not None:
                changes.append(change)
            if warning is not None:
                self._merge(warnings, [warning])

        required_capabilities = list(analysis["missing_capabilities"])

        if changes:
            status = PROPOSAL_CHANGE_RECOMMENDED
            reason = f"{len(changes)} change(s) proposed from {len(blockers)} observed blocker(s)."
        elif warnings:
            status = PROPOSAL_BLOCKED
            reason = (
                f"{len(blockers)} blocker(s) were observed, but none could be safely "
                "resolved with an automatic plan change; see warnings."
            )
        else:
            # Defensive fallback - should not occur, since every known
            # blocker type above produces either a change or a warning.
            status = PROPOSAL_BLOCKED
            reason = f"{len(blockers)} blocker(s) were observed; no automatic changes were proposed."

        proposal = PlanProposal(
            goal_id, plan_id, status, reason,
            source_blockers=source_blockers, proposed_changes=changes,
            affected_steps=affected_steps, required_capabilities=required_capabilities,
            warnings=warnings,
        )
        return proposal.to_dict()

    def validate_proposal(self, proposal):
        """Validate a proposal's *shape*, not its judgment: whether
        `proposal` (either a plain dict as returned by `propose`, or a
        `PlanProposal` instance) has every required field, a
        recognized `status`, and - for each proposed change - a
        recognized `change_type`, a `target_step_id` that actually
        exists in the referenced Plan (when not `None`), safe
        structured `proposed_data`, and a `confidence` that is a
        number in `[0.0, 1.0]` (requirement 15).

        Read-only: only ever reads from `plan_manager` to confirm a
        `target_step_id` exists - never creates, modifies, or removes
        anything.

        Returns `{"valid": bool, "failed_checks": [...], "warnings": [...]}`;
        each entry in `failed_checks` is `{"check": <CHECK_* name>,
        "reason": <str>}` - same shape convention
        `execution/preflight.py`'s `PreflightResult` already uses."""
        if hasattr(proposal, "to_dict"):
            proposal = proposal.to_dict()

        failed_checks = []
        warnings = []

        if not isinstance(proposal, dict):
            failed_checks.append({
                "check": CHECK_STRUCTURE,
                "reason": f"proposal must be a dict (or expose to_dict()), got {type(proposal).__name__}.",
            })
            return {"valid": False, "failed_checks": failed_checks, "warnings": warnings}

        missing_keys = [key for key in _REQUIRED_PROPOSAL_KEYS if key not in proposal]
        if missing_keys:
            failed_checks.append({
                "check": CHECK_STRUCTURE,
                "reason": f"proposal is missing required key(s): {missing_keys!r}.",
            })

        status = proposal.get("status")
        if status not in ALL_PROPOSAL_STATUSES:
            failed_checks.append({
                "check": CHECK_STATUS_VALID,
                "reason": f"Unknown proposal status: {status!r}.",
            })

        plan_id = proposal.get("plan_id")
        plan = self._plan_manager.get_plan(plan_id) if plan_id is not None else None

        changes = proposal.get("proposed_changes")
        if not isinstance(changes, list):
            failed_checks.append({
                "check": CHECK_STRUCTURE,
                "reason": f"proposed_changes must be a list, got {type(changes).__name__}.",
            })
            changes = []

        for change in changes:
            if hasattr(change, "to_dict"):
                change = change.to_dict()
            if not isinstance(change, dict):
                failed_checks.append({
                    "check": CHECK_STRUCTURE,
                    "reason": f"a proposed change must be a dict, got {type(change).__name__}.",
                })
                continue

            change_ref = change.get("change_id", "<unknown change_id>")

            missing_change_keys = [key for key in _REQUIRED_CHANGE_KEYS if key not in change]
            if missing_change_keys:
                failed_checks.append({
                    "check": CHECK_STRUCTURE,
                    "reason": f"change {change_ref!r} is missing required key(s): {missing_change_keys!r}.",
                })

            change_type = change.get("change_type")
            if change_type not in ALL_CHANGE_TYPES:
                failed_checks.append({
                    "check": CHECK_CHANGE_TYPE_VALID,
                    "reason": f"change {change_ref!r} has an unknown change_type: {change_type!r}.",
                })

            target_step_id = change.get("target_step_id")
            if target_step_id is not None:
                if plan is None or self._plan_manager.get_step(plan_id, target_step_id) is None:
                    failed_checks.append({
                        "check": CHECK_TARGET_STEP_VALID,
                        "reason": (
                            f"change {change_ref!r} targets step_id {target_step_id!r}, "
                            f"which does not exist in plan {plan_id!r}."
                        ),
                    })

            try:
                ensure_structured_data(change.get("proposed_data"))
            except TypeError as exc:
                failed_checks.append({
                    "check": CHECK_PROPOSED_DATA_SAFE,
                    "reason": f"change {change_ref!r} has unsafe proposed_data: {exc}",
                })

            confidence = change.get("confidence")
            if (
                isinstance(confidence, bool)
                or not isinstance(confidence, (int, float))
                or not (0.0 <= float(confidence) <= 1.0)
            ):
                failed_checks.append({
                    "check": CHECK_CONFIDENCE_VALID,
                    "reason": f"change {change_ref!r} has an invalid confidence value: {confidence!r}.",
                })

        return {"valid": not failed_checks, "failed_checks": failed_checks, "warnings": warnings}
