"""
Agent - Code Change Self-Upgrade Validation
================================================
Prompt 350: strengthens the existing CODE_CHANGE Self-Upgrade adapter
(agent/code_change_self_upgrade_adapter.py, Prompt 349) by connecting
it to the existing Self-Upgrade validation/sandbox stage
(self_upgrade/sandbox.py's `Sandbox`) - never a second adapter, never
a second sandbox, and never any part of `UpgradeSystem.propose_upgrade`
beyond that one existing, already-working sandbox check:

    {correction_result, original_fragment, replacement, test_status}
        -> build_code_change_self_upgrade_readiness()
        -> {status, reason, target_file}

Reuses, never duplicates:
  - `agent.code_change_self_upgrade_adapter.
    build_self_upgrade_input_from_code_correction` (Prompt 349) is
    called directly, unchanged, to decide the exact same "was this
    proposal validated safe *and* was the change actually, successfully
    applied" question it already answers (requirement 1) - this module
    never re-reads `validation_result`/`application` a second,
    disagreeing way, and never re-implements that gate. Its own
    `STATUS_ACCEPTED`/`STATUS_REJECTED` result - and, for a rejection,
    its own already-worded `reason` - is reused verbatim wherever this
    module reports "validation failed" or "the change was not
    successfully applied" (requirement 4's first two rejection cases
    are nothing but that adapter's own `REJECTED` case, reused as-is).
  - `agent.test_result_evaluation.RESULT_PASSED`/
    `ALL_TEST_RESULT_CLASSIFICATIONS` - the exact same test-outcome
    vocabulary `agent.code_correction_retest`/`agent.code_change_
    evaluation` already use - are imported, unchanged, to decide "did
    the relevant test pass" (requirement 4's third rejection case) and
    to recognize a well-formed `test_status` value at all (requirement
    3/4's "required metadata"). This module never runs a test itself
    and never re-classifies a raw test result - `test_status` is
    always supplied already-classified by a caller (typically
    `agent.code_correction_retest.build_code_correction_retest(...)
    ["retest_evaluation"]["classification"]`, or `agent.code_change_
    evaluation.build_code_change_evaluation(...)["test_status"]`).
  - `self_upgrade.sandbox.Sandbox` (self_upgrade/sandbox.py,
    unchanged) is instantiated (or accepted, already-built, from a
    caller) and its own `run(payload)` method is called exactly once,
    on the one already-accepted `self_upgrade_input["payload"]` the
    reused adapter above produced - this *is* "the existing
    Self-Upgrade validation/sandbox stage" requirement 2 asks this
    module to connect to (requirements 2, 8). Nothing here
    re-implements `Sandbox`'s own structural payload check, and
    nothing here calls `UpgradeSystem.propose_upgrade` (which would
    also install and version the upgrade) - only the one, existing,
    non-mutating `Sandbox.run` step is reused.

This is a readiness *check*, never an install/activation step
(requirement 6): nothing in this module calls `UpgradeSystem.
propose_upgrade`, `UpgradeSystem._advance`, or
`self_upgrade.version_system.VersionSystem.create_version`/
`rollback_to` - no upgrade record is ever created, no stage is ever
advanced, no version is ever recorded, and no file is ever installed
or activated. `self_upgrade.version_system.VersionSystem`'s own
rollback/version behavior is left completely untouched - this module
never imports, calls, or otherwise interacts with it at all
(requirement 7: "preserve rollback/version behavior").

`status` (requirement 5) is exactly one of:
    `READY`    - every one of the four checks below passed: required
                 metadata is present, the reused adapter accepted the
                 change, the relevant test passed, and the existing
                 `Sandbox` reports the resulting payload as
                 structurally valid.
    `REJECTED` - any of the four checks failed - see requirement 4;
                 `reason` always explains exactly which one, reusing
                 an already-computed explanation (the adapter's own
                 `reason`, or `Sandbox`'s own `details`) wherever one
                 already exists, rather than inventing a second,
                 differently-worded one.

The four checks (requirement 4), in the fixed order they are run and
reported in:
  1. required metadata is present - `target_file`/`original_fragment`
     are non-empty strings, `replacement` is a string, and
     `test_status` is one of `ALL_TEST_RESULT_CLASSIFICATIONS` -
     checked first, since every later check assumes these are usable.
  2. the reused adapter's own verdict is `ACCEPTED` (requirement 4's
     "validation failed" / "the change was not successfully applied" -
     both already covered by that one existing gate, never
     re-implemented here).
  3. `test_status == RESULT_PASSED` (requirement 4's "the relevant
     test did not pass").
  4. the existing `Sandbox.run(...)` on the resulting payload reports
     `passed=True` (requirement 2, 8 - the actual connection to the
     existing validation/sandbox stage).

Checked in that fixed order, and this function returns as soon as one
fails - same "one concrete reason, never a merged list" convention
`agent.code_correction_proposal_validation.
build_code_correction_proposal_validation` already follows.

Never raises: any input that is missing or malformed at any of the
four checks above is reported as `status=REJECTED` with an explanatory
`reason`, exactly like every other module in this project's correction
pipeline already guarantees.
"""

from .code_change_self_upgrade_adapter import (
    STATUS_ACCEPTED as ADAPTER_STATUS_ACCEPTED,
    build_self_upgrade_input_from_code_correction,
)
from .test_result_evaluation import RESULT_PASSED, ALL_TEST_RESULT_CLASSIFICATIONS
from self_upgrade.sandbox import Sandbox

STATUS_READY = "READY"
STATUS_REJECTED = "REJECTED"

ALL_SELF_UPGRADE_READINESS_STATUSES = (STATUS_READY, STATUS_REJECTED)

_REASON_MISSING_METADATA = (
    "The code change is missing required metadata (target_file, "
    "original_fragment, replacement, and a recognized test_status are "
    "all required)."
)
_REASON_TEST_NOT_PASSED = (
    "The relevant test did not pass; the change cannot proceed to "
    "Self-Upgrade."
)


def _has_required_metadata(target_file, original_fragment, replacement, test_status):
    """Requirement 3/4: the four pieces of metadata a code change must
    carry before this stage will even consider it. Never guesses at a
    missing value - a falsy/wrong-typed field is simply "missing"."""
    if not isinstance(target_file, str) or not target_file:
        return False
    if not isinstance(original_fragment, str) or not original_fragment:
        return False
    if not isinstance(replacement, str):
        return False
    if test_status not in ALL_TEST_RESULT_CLASSIFICATIONS:
        return False
    return True


def build_code_change_self_upgrade_readiness(
    correction_result, original_fragment, replacement, test_status, sandbox=None,
):
    """Build the small, structured `{status, reason, target_file}`
    result that decides whether an already-validated, already-applied,
    already-retested code change is READY to be handed to the existing
    Self-Upgrade pipeline - or REJECTED. See module docstring for the
    full, fixed gating rules.

    `correction_result` is expected to be exactly what
    `AgentLoop.apply_code_correction(...)` (agent/agent_loop.py,
    Prompt 343) already returns - the same input the existing
    `build_self_upgrade_input_from_code_correction` (Prompt 349)
    accepts, reused here unchanged.

    `original_fragment`/`replacement` are the concrete source fragment
    and its replacement - the exact `old_text`/`new_text` a caller
    already supplied to `apply_code_correction` - supplied again here
    explicitly, since nothing in `correction_result` itself carries
    them (see `agent.code_correction_application`'s own docstring).

    `test_status` is an already-classified test outcome - typically
    `agent.code_correction_retest.build_code_correction_retest(...)
    ["retest_evaluation"]["classification"]` - one of
    `agent.test_result_evaluation.ALL_TEST_RESULT_CLASSIFICATIONS`.
    This function never runs a test itself.

    `sandbox`, if given, must be a `self_upgrade.sandbox.Sandbox`
    instance (or provide a compatible `run(payload)` method) - reused
    exactly as provided, same "caller may inject a collaborator,
    otherwise one is built" convention `UpgradeSystem.__init__` itself
    already follows for its own `Sandbox`. Omitted, a fresh
    `Sandbox()` is used.

    Always returns:
        {
            "status": <"READY" or "REJECTED" - see module docstring>,
            "reason": <str naming exactly the one check that failed,
                      or, for READY, a short confirming message>,
            "target_file": <the target file this readiness check was
                      for, or None when it could not even be
                      determined>,
        }

    Never installs, activates, versions, or permanently modifies
    anything - see module docstring. Never raises: any malformed input
    is reported as `status=REJECTED` with an explanatory `reason`."""
    is_dict = isinstance(correction_result, dict)
    application = correction_result.get("application") if is_dict else None
    target_file = application.get("target_file") if isinstance(application, dict) else None

    # Check 1: required metadata (requirement 3, 4).
    if not _has_required_metadata(target_file, original_fragment, replacement, test_status):
        return {
            "status": STATUS_REJECTED,
            "reason": _REASON_MISSING_METADATA,
            "target_file": target_file if isinstance(target_file, str) and target_file else None,
        }

    # Check 2: reused Prompt-349 adapter - covers both "validation
    # failed" and "the change was not successfully applied"
    # (requirement 1, 4) without re-implementing either check.
    adapter_result = build_self_upgrade_input_from_code_correction(correction_result)
    if adapter_result["status"] != ADAPTER_STATUS_ACCEPTED:
        return {
            "status": STATUS_REJECTED,
            "reason": adapter_result["reason"],
            "target_file": target_file,
        }

    # Check 3: the relevant test must have passed (requirement 4).
    if test_status != RESULT_PASSED:
        return {
            "status": STATUS_REJECTED,
            "reason": _REASON_TEST_NOT_PASSED,
            "target_file": target_file,
        }

    # Check 4: connect to the existing Self-Upgrade validation/sandbox
    # stage (requirement 2, 8) - never a new sandbox, never
    # `UpgradeSystem.propose_upgrade`'s install/version stages.
    payload = dict(adapter_result["self_upgrade_input"]["payload"])
    payload["original_fragment"] = original_fragment
    payload["replacement"] = replacement
    payload["test_status"] = test_status

    active_sandbox = sandbox if sandbox is not None else Sandbox()
    sandbox_result = active_sandbox.run(payload)
    if not sandbox_result.passed:
        return {
            "status": STATUS_REJECTED,
            "reason": sandbox_result.details,
            "target_file": target_file,
        }

    return {
        "status": STATUS_READY,
        "reason": (
            f"Code change to {target_file!r} passed validation, application, "
            "retest, and the Self-Upgrade sandbox check; ready for Self-Upgrade."
        ),
        "target_file": target_file,
    }
