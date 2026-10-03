"""
Self-Upgrade - Capability Creation Plan
===========================================
`build_capability_creation_plan` connects the existing, already-
computed Self-Upgrade-request analysis
(`planning.adaptive_plan_analyzer.AdaptivePlanAnalyzer.
analyze_self_upgrade_request`, Prompt 358 - itself built on
`self_upgrade.self_upgrade_request.SelfUpgradeRequest`, Prompt 357) to
one small, structured `CapabilityCreationPlan`:

    SelfUpgradeRequest (Prompt 357)
        -> AdaptivePlanAnalyzer.analyze_self_upgrade_request (Prompt 358)
        -> {request_id, goal, requested_capability, required_capabilities,
            affected_systems, blockers, warnings}
        -> build_capability_creation_plan()
        -> {request_id, capability_name, purpose, required_capabilities,
            affected_systems, implementation_steps, blockers, status}

This is a small *adapter* - the same "dict in, dict out, nothing
hidden" shape already used by
`agent.code_change_self_upgrade_adapter.
build_self_upgrade_input_from_code_correction` - never a second,
general-purpose planning system (requirement: "do not create a second
general planning system"). It never re-runs the analysis itself: every
one of `request_id`, `goal`, `requested_capability`,
`required_capabilities`, `affected_systems`, and `blockers` is read
directly off the `analysis` dict this module is handed and reported
unchanged - this module only ever *adds* a `purpose` label (the
analysis's own `goal`, verbatim), a fixed `status`, and a small set of
deterministic, fixed-wording `implementation_steps`.

It does not generate source code, does not modify any project file,
and does not execute, install, sandbox, or version anything
(requirements 6, 7, 8): there is no file I/O, no dynamic code
execution (`eval`/`exec`/`subprocess`), and no import of, or call
into, `self_upgrade.upgrade_system.UpgradeSystem`,
`self_upgrade.sandbox.Sandbox`, or `self_upgrade.version_system.
VersionSystem` anywhere in this module. `implementation_steps` are
plain, human-readable strings describing *what a future stage would
still need to do* - never code, never a diff, never a file path to
write to.

Status vocabulary (requirement 4) - always exactly one of:
    `INVALID`  - the analysis itself reports an invalid/incomplete
                 request (no usable `request_id`/`requested_capability`,
                 or the analysis's own blockers include the
                 `INVALID_REQUEST` type `AdaptivePlanAnalyzer.
                 analyze_self_upgrade_request` already reports for a
                 malformed `SelfUpgradeRequest` - see that module's own
                 docstring). Never guessed - read straight off what the
                 analysis already recorded.
    `BLOCKED`  - the request itself is well-formed, but the analysis
                 recorded at least one other blocker (missing/
                 unavailable capability, missing handler), or couldn't
                 determine `required_capabilities`/`affected_systems`
                 at all (requirement 5: "return BLOCKED when required
                 information is missing" - this module never invents a
                 capability name or an affected system that the
                 analysis itself didn't already report).
    `READY`    - the analysis recorded zero blockers and both
                 `required_capabilities` and `affected_systems` are
                 non-empty.

`implementation_steps` is only ever populated for a `READY` plan
(requirement 3: "must contain only small, deterministic steps derived
from the analysis") - a `BLOCKED`/`INVALID` plan has no steps to
propose yet, since there is nothing safe to plan around a capability
this project doesn't yet know is registered, handled, or even
well-specified. Every step name is built from a small, fixed template
applied to `capability_name`/`affected_systems` - the exact same
template every time for the same input (requirement 3:
"deterministic"), never phrased differently call to call.

Never raises: a malformed `analysis` (not a dict, or missing expected
keys) is reported as an `INVALID` plan with an explanatory blocker,
the same "always return a structured, honest verdict" convention
`agent.code_change_self_upgrade_adapter` and
`self_upgrade.self_upgrade_request.SelfUpgradeRequest.is_valid` both
already follow.
"""

from datetime import datetime, timezone

from planning.adaptive_plan_analyzer import BLOCKER_INVALID_REQUEST

STATUS_READY = "READY"
STATUS_BLOCKED = "BLOCKED"
STATUS_INVALID = "INVALID"

ALL_STATUSES = (STATUS_READY, STATUS_BLOCKED, STATUS_INVALID)


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _invalid_analysis_blocker(reason):
    """One fixed-shape blocker record for a malformed `analysis`
    argument itself - same `{blocker_id, type, description, source,
    step_id, severity, evidence}` shape
    `planning.adaptive_plan_analyzer.Blocker.to_dict()` already
    produces, so a `CapabilityCreationPlan`'s `blockers` list is always
    uniformly shaped whether its blockers came from the analysis or
    from this module itself - never a second, differently-shaped
    blocker format."""
    return {
        "blocker_id": "blocker-capability-creation-plan-1",
        "type": BLOCKER_INVALID_REQUEST,
        "description": reason,
        "source": "capability_creation_plan",
        "step_id": None,
        "severity": "critical",
        "evidence": [],
    }


def _implementation_steps(capability_name, affected_systems):
    """Small, fixed, deterministic set of implementation steps -
    always the same wording for the same `capability_name`/
    `affected_systems` (requirement 3). Describes *what to do*, never
    *how* - no source code, no file contents, no diff (requirement 6)."""
    steps = [
        f"Review the self-upgrade analysis for capability {capability_name!r}.",
        f"Design the interface/contract for capability {capability_name!r}.",
    ]
    for system in affected_systems:
        steps.append(
            f"Implement the capability logic within the existing module "
            f"{system!r}."
        )
    steps.append(
        f"Register capability {capability_name!r} with the project's "
        "capability_system."
    )
    steps.append(
        f"Register a handler for capability {capability_name!r} with the "
        "project's capability_handlers registry."
    )
    steps.append(f"Add focused tests covering the new {capability_name!r} capability.")
    return steps


def _plan(
    request_id, capability_name, purpose, required_capabilities,
    affected_systems, implementation_steps, blockers, status,
):
    return {
        "request_id": request_id,
        "capability_name": capability_name,
        "purpose": purpose,
        "required_capabilities": list(required_capabilities),
        "affected_systems": list(affected_systems),
        "implementation_steps": list(implementation_steps),
        "blockers": list(blockers),
        "status": status,
        "created_at": _now_iso(),
    }


def build_capability_creation_plan(analysis):
    """Build one `CapabilityCreationPlan` dict from `analysis` - the
    exact dict `AdaptivePlanAnalyzer.analyze_self_upgrade_request`
    already returns (Prompt 358). See module docstring for the full
    status/step rules. Always returns:

        {
            "request_id": <analysis["request_id"], unchanged>,
            "capability_name": <analysis["requested_capability"],
                                unchanged>,
            "purpose": <analysis["goal"], unchanged>,
            "required_capabilities": <analysis["required_capabilities"],
                                     unchanged>,
            "affected_systems": <analysis["affected_systems"], unchanged>,
            "implementation_steps": [...] (only for READY - see above),
            "blockers": <analysis["blockers"], unchanged, plus this
                        module's own blocker only when `analysis` itself
                        is malformed>,
            "status": "READY" | "BLOCKED" | "INVALID",
            "created_at": <ISO-8601 timestamp>,
        }

    Never mutates `analysis`. Never generates source code, never
    modifies a project file, and never executes, installs, sandboxes,
    or versions anything - see module docstring."""
    if not isinstance(analysis, dict):
        return _plan(
            None, None, None, [], [], [],
            [_invalid_analysis_blocker(
                "No self-upgrade analysis was available to build a "
                "CapabilityCreationPlan from."
            )],
            STATUS_INVALID,
        )

    request_id = analysis.get("request_id")
    capability_name = analysis.get("requested_capability")
    purpose = analysis.get("goal")
    required_capabilities = list(analysis.get("required_capabilities") or [])
    affected_systems = list(analysis.get("affected_systems") or [])
    blockers = list(analysis.get("blockers") or [])

    blocker_types = {b.get("type") for b in blockers if isinstance(b, dict)}

    if request_id is None or capability_name is None or BLOCKER_INVALID_REQUEST in blocker_types:
        status = STATUS_INVALID
    elif blockers or not required_capabilities or not affected_systems:
        status = STATUS_BLOCKED
    else:
        status = STATUS_READY

    implementation_steps = (
        _implementation_steps(capability_name, affected_systems)
        if status == STATUS_READY else []
    )

    return _plan(
        request_id, capability_name, purpose, required_capabilities,
        affected_systems, implementation_steps, blockers, status,
    )
