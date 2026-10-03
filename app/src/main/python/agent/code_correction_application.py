"""
Agent - Code Correction Application
========================================
Connects the existing proposal-validation result
(agent/code_correction_proposal_validation.py, Prompt 342) to the
existing, already-working "plan an exact-fragment change, then apply
it only if the plan is ready" system
(execution/code_change_apply_capability.py) - never a second,
differently-behaving edit or proposal system:

    validation_result (VALID + is_safe_to_apply)
        + old_text, new_text (the concrete fragment a caller supplies -
          CodeCorrectionProposal never invents one, see Prompt 341)
        -> build_code_correction_application()
        -> {status, target_file, changed, error}

Reuses, never duplicates:
  - `execution.code_change_apply_capability.make_code_change_apply_handler`
    is called directly, unchanged, to do the actual work: it already
    re-plans the one-fragment change via the existing `code_change_plan`
    capability (exact-occurrence-count safety rule, `.py`-only,
    allowed-directory containment, AST validity - requirement 5) and
    applies it - by calling the existing `text_file_edit` capability's
    own handler exactly once - only when that plan comes back
    `ready_to_apply` (requirement 6). This module adds no fragment-
    matching, path-safety, or file-writing logic of its own; it only
    decides *whether* to call that existing handler at all (requirement
    3's VALID + is_safe_to_apply gate) and reshapes its result into
    the small structure this project's correction pipeline already
    uses elsewhere in agent/ (requirement 8).
  - The gate itself (requirement 3) reads nothing but
    `validation_result["status"]`/`["is_safe_to_apply"]` - the exact
    fields `build_code_correction_proposal_validation` (Prompt 342)
    already computed - never re-validating the proposal a second,
    disagreeing way; a rejected `validation_result`'s own `reason` is
    reused verbatim as this module's `error`, rather than a second,
    differently-worded explanation being invented.

`target_file` is read *only* from `validation_result["target_file"]` -
this module's `build_code_correction_application` takes no separate
`path`/`target_file` parameter a caller could supply instead, so it is
structurally impossible for this module to ever write to a file other
than the one that was actually validated (requirement 7: "never
overwrite an unrelated file").

Applies at most one change per call (requirement 4, 11): the reused
`code_change_apply` handler itself already calls `text_file_edit`'s
write path at most once per invocation (see that module's own
docstring), and this function calls that reused handler exactly once,
never in a loop and never a second time for the same or a different
fragment - there is no retry of any kind here, and nothing in this
module ever decides *what* a second correction should be. The modified
file is never imported, run, or otherwise executed by this module
(requirement 10) - applying a change here only ever means the one
`str.replace`-based text write `text_file_edit`'s own handler already
performs, exactly as `code_change_apply` itself documents.

`status` is exactly one of:
    `APPLIED`   - the plan was ready and the one fragment was
                  successfully replaced (`changed=True`).
    `NOT_READY` - the plan was not ready (the fragment could not be
                  uniquely identified, or the file is not currently
                  valid Python) - requirement 6 - or no usable
                  `old_text` was supplied at all; the file is left
                  completely untouched either way (`changed=False`).
    `REJECTED`  - `validation_result` was not `VALID`/`is_safe_to_apply`
                  to begin with - this module never even attempts a
                  write (`changed=False`).
    `ERROR`     - the reused handler raised for an underlying safety
                  precondition (e.g. the file no longer exists, or the
                  path is no longer within the allowed directories) -
                  reported, never propagated, with `changed=False`.

Never raises: every precondition failure the reused `code_change_apply`
handler itself may raise for is caught here and reported as
`status=ERROR` instead - the same "always return a structured, honest
verdict" convention every other module in this project's correction
pipeline already follows. `validation_result`/the caller-supplied
`old_text`/`new_text` are only ever read, never mutated (requirement
9: "preserve the original proposal and validation result" - enforced
at the `AgentLoop` level below by returning them alongside, completely
unchanged).
"""

from execution.code_change_apply_capability import make_code_change_apply_handler

STATUS_APPLIED = "APPLIED"
STATUS_NOT_READY = "NOT_READY"
STATUS_REJECTED = "REJECTED"
STATUS_ERROR = "ERROR"

ALL_CODE_CORRECTION_APPLICATION_STATUSES = (
    STATUS_APPLIED, STATUS_NOT_READY, STATUS_REJECTED, STATUS_ERROR,
)


def _validation_metadata_error(change_metadata):
    """Turn the reused `code_change_apply` plan's own
    `validation_status`/`analysis_summary` (requirement 5's fragment-
    uniqueness and AST-validity checks) into one human-readable
    string - reading only what that plan already computed, never
    inventing a diagnosis of its own."""
    validation_status = (change_metadata or {}).get("validation_status") or {}
    analysis_summary = (change_metadata or {}).get("analysis_summary") or {}
    errors = list(validation_status.get("errors") or [])
    if not analysis_summary.get("valid", True):
        errors.append(f"File is not valid Python: {analysis_summary.get('syntax_error')}")
    return "; ".join(errors) if errors else "The correction could not be applied."


def build_code_correction_application(validation_result, old_text, new_text, allowed_dirs=None):
    """Apply, at most, the one validated correction `validation_result`
    describes, using only the existing `code_change_apply` system - see
    module docstring for the full reuse/gating rules.

    Always returns:
        {
            "status": <"APPLIED"/"NOT_READY"/"REJECTED"/"ERROR" - see
                      module docstring>,
            "target_file": <validation_result["target_file"], or None>,
            "changed": <bool - True only for APPLIED>,
            "error": <str explaining why nothing was applied, or None
                     for APPLIED>,
        }

    Applies a change (requirement 3) only when `validation_result` is
    a dict with `status == "VALID"` and `is_safe_to_apply == True` -
    both already-computed facts, read directly. `old_text` must be a
    non-empty string (the fragment to replace) and `new_text` a string
    (the replacement, which may be empty) - missing either is reported
    as `NOT_READY`, never guessed at.

    `allowed_dirs`, if given, is forwarded unchanged to the reused
    `code_change_apply` handler; omitted, the application's real
    default safe directories are used.

    Never raises: a precondition the reused handler itself raises for
    (an unsafe path, a non-`.py` file, a missing file, ...) is caught
    here and reported as `status=ERROR` instead."""
    is_dict = isinstance(validation_result, dict)
    target_file = validation_result.get("target_file") if is_dict else None

    if not is_dict or validation_result.get("status") != "VALID" or not validation_result.get("is_safe_to_apply"):
        reason = validation_result.get("reason") if is_dict else None
        return {
            "status": STATUS_REJECTED,
            "target_file": target_file,
            "changed": False,
            "error": reason or "The correction proposal was not validated as safe to apply.",
        }

    if not isinstance(old_text, str) or not old_text:
        return {
            "status": STATUS_NOT_READY,
            "target_file": target_file,
            "changed": False,
            "error": "No source fragment was provided; the correction cannot be applied.",
        }
    if not isinstance(new_text, str):
        return {
            "status": STATUS_NOT_READY,
            "target_file": target_file,
            "changed": False,
            "error": "No replacement text was provided; the correction cannot be applied.",
        }

    handler = make_code_change_apply_handler(allowed_dirs=allowed_dirs)
    try:
        result = handler({"path": target_file, "old_text": old_text, "new_text": new_text})
    except (ValueError, OSError, TypeError) as exc:
        return {
            "status": STATUS_ERROR,
            "target_file": target_file,
            "changed": False,
            "error": str(exc),
        }

    if not result.get("change_applied"):
        return {
            "status": STATUS_NOT_READY,
            "target_file": result.get("path", target_file),
            "changed": False,
            "error": _validation_metadata_error(result.get("change_metadata")),
        }

    return {
        "status": STATUS_APPLIED,
        "target_file": result.get("path", target_file),
        "changed": True,
        "error": None,
    }
