"""
Agent - Code Change Self-Upgrade Adapter
=============================================
Connects the existing, already-validated code-correction result
(agent/agent_loop.py's `AgentLoop.apply_code_correction` -
`{proposal, validation_result, application}`, Prompt 343, itself built
from `agent.code_correction_proposal.build_code_correction_proposal`
(Prompt 341) + `agent.code_correction_proposal_validation.
build_code_correction_proposal_validation` (Prompt 342) +
`agent.code_correction_application.build_code_correction_application`
(Prompt 343)) to the existing Self-Upgrade pipeline
(self_upgrade/upgrade_system.py's `UpgradeSystem.propose_upgrade`,
self_upgrade/version_system.py, self_upgrade/sandbox.py) - a small,
one-way *adapter*, never a second correction system and never a second
Self-Upgrade system:

    {proposal, validation_result, application}
        -> build_self_upgrade_input_from_code_correction()
        -> {status, reason, self_upgrade_input}

Reuses, never duplicates:
  - `agent.code_correction_proposal_validation.VALIDATION_STATUS_VALID`
    and `agent.code_correction_application.STATUS_APPLIED` are
    imported, unchanged, as the two already-existing "this step
    succeeded" vocabularies this module gates on - it never
    re-validates a proposal, never re-applies a change, and never
    invents a third vocabulary for "was this safe/applied".
  - `self_upgrade.upgrade_system.UpgradeSystem.propose_upgrade(name,
    description, payload=None)` is this module's only intended
    downstream consumer - `self_upgrade_input` below is shaped as
    exactly the `{"name", "description", "payload"}` keyword arguments
    that call already accepts, so a caller can hand it straight to
    `UpgradeSystem.propose_upgrade(**self_upgrade_input)`. This module
    never calls `propose_upgrade` itself, never touches
    `self_upgrade.sandbox.Sandbox` or `self_upgrade.version_system.
    VersionSystem` directly, and never creates a new `UpgradeSystem` -
    it only prepares the input `UpgradeSystem`'s own, already-existing
    pipeline expects (requirement: "do not install or activate an
    upgrade automatically in this step").
  - `self_upgrade.sandbox.Sandbox.REQUIRED_PAYLOAD_FIELDS` (`"name"`,
    `"description"`) is the exact reason `payload` below always
    carries its own `"name"`/`"description"` keys (duplicated from the
    top-level `self_upgrade_input` fields) - so the eventual
    `Sandbox.run(payload)` call inside `propose_upgrade` already has
    what it structurally requires, without this module re-implementing
    any sandbox/validation logic of its own.

This is an adapter, not a new pipeline (requirements 8, 9): it never
re-derives whether the original proposal was safe (that is exactly
`validation_result["status"]`/`["is_safe_to_apply"]`,
`agent.code_correction_proposal_validation`'s own, already-computed
verdict) and never re-derives whether the change was actually applied
(that is exactly `application["status"]`/`["changed"]`,
`agent.code_correction_application`'s own, already-computed verdict).
It reads those two already-existing facts and nothing else to decide
whether to produce a Self-Upgrade input at all.

`status` (requirement: "clearly identify accepted vs rejected") is
exactly one of:
    `ACCEPTED` - the validation was `VALID`/`is_safe_to_apply`, *and*
                 the application actually succeeded (`status ==
                 STATUS_APPLIED` and `changed is True`) - only then is
                 a `self_upgrade_input` built.
    `REJECTED` - anything else: a malformed `correction_result`, a
                 validation result that was never `VALID`/safe (an
                 invalid or not-ready proposal - requirement 6), or an
                 application that did not actually succeed (rejected,
                 not-ready, or errored - requirement 6, "failed changes
                 must not enter the Self-Upgrade pipeline"). `reason`
                 always names which of the two checks failed, reusing
                 `application["error"]`/`validation_result["reason"]`
                 verbatim wherever one is already available, rather
                 than inventing a new, second explanation.

Preserves everything requirement 4 asks for, unchanged, under the
built `self_upgrade_input["payload"]`:
    - `target_file`  - read from `application["target_file"]` (the
                       file the change was actually applied to), never
                       a second, possibly-different path;
    - `proposal`     - the exact, original `correction_result
                       ["proposal"]`, completely unmodified;
    - `validation_result` - the exact, original `correction_result
                       ["validation_result"]`, completely unmodified;
    - `change_result` - the exact, original `correction_result
                       ["application"]`, completely unmodified (this
                       is the "change result" requirement 4 asks to
                       preserve - the same dict `apply_code_correction`
                       itself already returns as `"application"`).

`payload["change_type"]` (requirement: "must clearly identify the
change as CODE_CHANGE") is always the fixed constant
`UPGRADE_TYPE_CODE_CHANGE = "CODE_CHANGE"` whenever `status` is
`ACCEPTED` - never anything else, never omitted, never guessed at from
the proposal's own `error_type`.

Never installs, activates, versions, sandboxes, or executes anything
(requirements 7, 9, 10, 11 - "do not create a new Self-Upgrade
system", "do not duplicate versioning or sandbox logic", "do not
execute code again"): this module contains no call to
`UpgradeSystem`/`Sandbox`/`VersionSystem`, no file I/O, and no dynamic
code execution of any kind - it only reads already-computed dict
fields and assembles one small, structured, inert result.

Never raises: a `correction_result` that isn't a dict, or one whose
`validation_result`/`application` are missing or malformed, is
reported as `status=REJECTED` with an explanatory `reason` and
`self_upgrade_input=None` - the same "always return a structured,
honest verdict" convention every other module in this project's
correction pipeline already follows.
"""

from .code_correction_proposal_validation import VALIDATION_STATUS_VALID
from .code_correction_application import STATUS_APPLIED as APPLICATION_STATUS_APPLIED

STATUS_ACCEPTED = "ACCEPTED"
STATUS_REJECTED = "REJECTED"

ALL_SELF_UPGRADE_ADAPTER_STATUSES = (STATUS_ACCEPTED, STATUS_REJECTED)

# Fixed self-upgrade "kind" this adapter always produces (requirement
# 4) - never derived from the proposal's own error_type, never
# anything but this one constant.
UPGRADE_TYPE_CODE_CHANGE = "CODE_CHANGE"

_DEFAULT_DESCRIPTION = "Validated code correction applied to {target_file}."


def _rejection_reason(is_dict, validation_result, validation_ok, application, application_ok):
    """One fixed, honest explanation per way a correction result can
    fail to qualify - never a guess, only a report of which
    already-known precondition wasn't met (same convention
    agent.code_correction_proposal._not_ready_reason already uses)."""
    if not is_dict:
        return "No code correction result was available to convert."
    if not validation_ok:
        reason = (
            validation_result.get("reason")
            if isinstance(validation_result, dict) else None
        )
        return reason or (
            "The correction proposal was not validated as safe to apply; "
            "it cannot be sent to the Self-Upgrade pipeline."
        )
    if not application_ok:
        error = (
            application.get("error")
            if isinstance(application, dict) else None
        )
        return error or (
            "The code change was not successfully applied; it cannot be "
            "sent to the Self-Upgrade pipeline."
        )
    return "The code correction result could not be converted."


def build_self_upgrade_input_from_code_correction(correction_result):
    """Build the small, structured `{status, reason, self_upgrade_input}`
    result that decides whether - and how - an already-validated,
    already-applied code correction may enter the existing Self-Upgrade
    pipeline. See module docstring for the full gating/preservation
    rules.

    `correction_result` is expected to be exactly what
    `AgentLoop.apply_code_correction(...)` (agent/agent_loop.py,
    Prompt 343) already returns: `{"proposal", "validation_result",
    "application"}`. Nothing here re-validates the proposal or
    re-applies the change - both already-computed verdicts are read
    directly off `validation_result`/`application`.

    Always returns:
        {
            "status": <"ACCEPTED" or "REJECTED" - see module
                      docstring>,
            "reason": <str explaining the verdict>,
            "self_upgrade_input": <None for REJECTED; for ACCEPTED,
                {
                    "name": <str - a deterministic, fixed-shape label
                             naming the target file, never invented>,
                    "description": <str - proposal["change_description"]
                             when available, otherwise a small fixed
                             fallback naming the target file>,
                    "payload": {
                        "name": <same as top-level "name">,
                        "description": <same as top-level
                                        "description">,
                        "change_type": "CODE_CHANGE",
                        "target_file": <application["target_file"]>,
                        "proposal": <correction_result["proposal"],
                                    unmodified>,
                        "validation_result": <correction_result
                                    ["validation_result"], unmodified>,
                        "change_result": <correction_result
                                    ["application"], unmodified>,
                    },
                }>,
        }

    Only a validated (`VALIDATION_STATUS_VALID` +
    `is_safe_to_apply=True`) *and* successfully, actually applied
    (`STATUS_APPLIED` + `changed=True`) code change is ever converted
    (requirement 5); an invalid, not-ready, rejected, or errored
    proposal/change is always `REJECTED` and never produces a
    `self_upgrade_input` (requirement 6).

    Never installs or activates an upgrade, never touches
    `UpgradeSystem`/`Sandbox`/`VersionSystem`, and never executes
    anything - see module docstring. Never raises: any malformed input
    is reported as `status=REJECTED` with an explanatory `reason`."""
    is_dict = isinstance(correction_result, dict)
    proposal = correction_result.get("proposal") if is_dict else None
    validation_result = correction_result.get("validation_result") if is_dict else None
    application = correction_result.get("application") if is_dict else None

    validation_ok = (
        isinstance(validation_result, dict)
        and validation_result.get("status") == VALIDATION_STATUS_VALID
        and validation_result.get("is_safe_to_apply") is True
    )
    application_ok = (
        isinstance(application, dict)
        and application.get("status") == APPLICATION_STATUS_APPLIED
        and application.get("changed") is True
    )

    if not is_dict or not validation_ok or not application_ok:
        return {
            "status": STATUS_REJECTED,
            "reason": _rejection_reason(
                is_dict, validation_result, validation_ok, application, application_ok,
            ),
            "self_upgrade_input": None,
        }

    target_file = application.get("target_file")
    change_description = proposal.get("change_description") if isinstance(proposal, dict) else None
    description = change_description or _DEFAULT_DESCRIPTION.format(target_file=target_file)
    name = f"code_change:{target_file}"

    payload = {
        "name": name,
        "description": description,
        "change_type": UPGRADE_TYPE_CODE_CHANGE,
        "target_file": target_file,
        "proposal": proposal,
        "validation_result": validation_result,
        "change_result": application,
    }

    return {
        "status": STATUS_ACCEPTED,
        "reason": f"Validated, applied code change to {target_file!r} is ready for Self-Upgrade.",
        "self_upgrade_input": {
            "name": name,
            "description": description,
            "payload": payload,
        },
    }
