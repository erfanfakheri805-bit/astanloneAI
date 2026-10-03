"""
Self-Upgrade - Capability Correction Apply
===========================================
`apply_capability_correction` is the next focused stage after
capability correction analysis
(self_upgrade.capability_correction_analysis, Prompt 367): applying
exactly ONE controlled source change to the failed capability's file:

    CapabilityCorrectionAnalysisResult (READY_FOR_CORRECTION)
        + changes = [{old_text, new_text}]   (exactly one)
        -> apply_capability_correction(...)
        -> {capability_name, file_path, status, correction_applied,
            change_metadata, validation_result, code_validation,
            error, changes_requested, correction_analysis}

The concrete fragment must be supplied by the caller: the existing
`CodeCorrectionProposal` only describes the *kind* of correction and
never invents source text (Prompt 341), so this module does not
either. Exactly one change is required - zero, several, or a
malformed entry is `INVALID` and nothing is written; a list is never
silently reduced.

Reuses, never duplicates:
  - `agent.code_correction_proposal_validation.
    build_code_correction_proposal_validation` re-validates the
    proposal (PROPOSED, target file present, inside `allowed_dirs`) -
    the same check `AgentLoop.validate_code_correction_proposal` uses.
  - `execution.text_file_read_capability.make_text_file_read_handler`
    (read-only) supplies the current source, so the resulting source
    can be checked *before* anything is written.
  - `code_intelligence.python_inspector.inspect_source` (AST parse
    only, nothing executed) validates that the corrected source is
    still valid Python. The existing code_change plan only checks the
    file *before* the edit, so this closes the gap "a correction must
    not turn a valid capability into invalid Python".
  - `execution.code_change_apply_capability.make_code_change_apply_handler`
    performs the one write: it re-plans the fragment via the existing
    `code_change_plan` (exactly-one-occurrence, `.py`-only,
    allowed-directory rules) and applies it through the existing
    `text_file_edit` handler exactly once. No file is opened for
    writing in this module.

Status:
    APPLIED               - the one change was written.
    NO_CORRECTION_REQUIRED- upstream NO_CORRECTION_REQUIRED, or
                            `correction_required` is False.
    BLOCKED               - upstream BLOCKED; target is a protected
                            path; or the target is outside
                            `allowed_dirs`. Nothing written.
    INVALID               - malformed analysis, missing/not-PROPOSED
                            proposal, target mismatch, not exactly one
                            well-formed change, proposal validation
                            failed, fragment not found/ambiguous, or
                            the corrected source is not valid Python.
                            Nothing written.
    FAILED                - upstream FAILED, or the reused write path
                            itself failed. `correction_applied` is
                            False unless the write succeeded.

Protected files: the project has no built-in protected-file list, and
no rule that allows overriding one. `protected_paths` (optional,
caller-supplied) is checked by real path; a match is BLOCKED and there
is deliberately no override parameter.

Never executes or imports the corrected code, retries, retests,
registers or activates anything, or mutates its inputs. Never raises.
"""

import copy
import os

from agent.code_correction_application import _validation_metadata_error
from agent.code_correction_proposal import STATUS_PROPOSED
from agent.code_correction_proposal_validation import (
    build_code_correction_proposal_validation,
    VALIDATION_STATUS_VALID,
)
from code_intelligence.python_inspector import inspect_source
from execution.code_change_apply_capability import make_code_change_apply_handler
from execution.text_file_read_capability import make_text_file_read_handler
from self_upgrade.capability_correction_analysis import (
    STATUS_READY_FOR_CORRECTION,
    STATUS_NO_CORRECTION_REQUIRED as ANALYSIS_NO_CORRECTION_REQUIRED,
    STATUS_BLOCKED as ANALYSIS_BLOCKED,
    STATUS_INVALID as ANALYSIS_INVALID,
    STATUS_FAILED as ANALYSIS_FAILED,
    ALL_STATUSES as ALL_ANALYSIS_STATUSES,
)

STATUS_APPLIED = "APPLIED"
STATUS_INVALID = "INVALID"
STATUS_BLOCKED = "BLOCKED"
STATUS_FAILED = "FAILED"
STATUS_NO_CORRECTION_REQUIRED = "NO_CORRECTION_REQUIRED"

ALL_STATUSES = (
    STATUS_APPLIED, STATUS_INVALID, STATUS_BLOCKED, STATUS_FAILED,
    STATUS_NO_CORRECTION_REQUIRED,
)

_ANALYSIS_KEYS = ("capability_name", "status", "correction_proposal",
                  "correction_required", "failure_info")
# Exact wording of the reused validators' own safety errors.
_OUTSIDE_MARKER = "outside the allowed directories"


def _non_blank(value):
    return isinstance(value, str) and bool(value.strip())


def _result(analysis, status, file_path=None, error=None, change_metadata=None,
            validation_result=None, code_validation=None, changes_requested=None):
    is_dict = isinstance(analysis, dict)
    try:
        reference = copy.deepcopy(analysis)
    except Exception:
        reference = None
    return {
        "capability_name": analysis.get("capability_name") if is_dict else None,
        "file_path": file_path,
        "status": status,
        "correction_applied": status == STATUS_APPLIED,
        "change_metadata": change_metadata,
        "validation_result": validation_result,
        "code_validation": code_validation,
        "error": error,
        "changes_requested": changes_requested,
        "correction_analysis": reference,
    }


def _classify_error_text(message):
    return STATUS_BLOCKED if _OUTSIDE_MARKER in (message or "") else None


def apply_capability_correction(correction_analysis, changes, allowed_dirs=None,
                                protected_paths=None):
    """Apply exactly one caller-supplied `{old_text, new_text}` change
    to the capability file a READY_FOR_CORRECTION
    `CapabilityCorrectionAnalysisResult` identifies. See module
    docstring. `allowed_dirs` is forwarded unchanged to every reused
    component. `protected_paths` is an optional iterable of file paths
    that must never be modified. Never raises."""
    try:
        return _apply(correction_analysis, changes, allowed_dirs, protected_paths)
    except Exception as exc:  # pragma: no cover - defensive
        return _result(
            correction_analysis if isinstance(correction_analysis, dict) else None,
            STATUS_FAILED, error=f"Unexpected error: {type(exc).__name__}: {exc}")


def _apply(analysis, changes, allowed_dirs, protected_paths):
    if not isinstance(analysis, dict) or any(k not in analysis for k in _ANALYSIS_KEYS):
        return _result(analysis, STATUS_INVALID,
                       error="correction_analysis must be a CapabilityCorrectionAnalysisResult dict.")

    upstream = analysis["status"]
    if upstream not in ALL_ANALYSIS_STATUSES:
        return _result(analysis, STATUS_INVALID,
                       error=f"Unrecognized correction analysis status: {upstream!r}.")

    failure_info = analysis["failure_info"] if isinstance(analysis["failure_info"], dict) else {}
    file_path = failure_info.get("file_path")

    if upstream == ANALYSIS_NO_CORRECTION_REQUIRED:
        return _result(analysis, STATUS_NO_CORRECTION_REQUIRED, file_path=file_path)
    passthrough = {ANALYSIS_BLOCKED: STATUS_BLOCKED, ANALYSIS_INVALID: STATUS_INVALID,
                   ANALYSIS_FAILED: STATUS_FAILED}
    if upstream in passthrough:
        blockers = analysis.get("blockers") or []
        return _result(analysis, passthrough[upstream], file_path=file_path,
                       error=blockers[0] if blockers else f"Upstream correction analysis was {upstream}.")

    # upstream == READY_FOR_CORRECTION from here on.
    if not analysis["correction_required"]:
        return _result(analysis, STATUS_NO_CORRECTION_REQUIRED, file_path=file_path)

    proposal = analysis["correction_proposal"]
    if not isinstance(proposal, dict) or proposal.get("status") != STATUS_PROPOSED:
        return _result(analysis, STATUS_INVALID, file_path=file_path,
                       error="No usable (PROPOSED) correction proposal is present.")
    target_file = proposal.get("target_file")
    if not _non_blank(target_file):
        return _result(analysis, STATUS_INVALID, file_path=file_path,
                       error="The correction proposal has no valid target file.")
    if target_file != file_path:
        return _result(analysis, STATUS_INVALID, file_path=target_file,
                       error="The proposal's target file does not match the failed capability's file.")

    if not isinstance(changes, (list, tuple)) or len(changes) != 1:
        count = len(changes) if isinstance(changes, (list, tuple)) else None
        return _result(analysis, STATUS_INVALID, file_path=target_file, changes_requested=count,
                       error="Exactly one source change must be requested; multiple or "
                             "missing changes are never applied or reduced.")
    change = changes[0]
    old_text = change.get("old_text") if isinstance(change, dict) else None
    new_text = change.get("new_text") if isinstance(change, dict) else None
    if not _non_blank(old_text) or not isinstance(new_text, str):
        return _result(analysis, STATUS_INVALID, file_path=target_file, changes_requested=1,
                       error="The change needs a non-blank old_text and a string new_text.")
    if old_text == new_text:
        return _result(analysis, STATUS_INVALID, file_path=target_file, changes_requested=1,
                       error="The change would not alter the source.")

    real_target = os.path.realpath(target_file)
    protected = {os.path.realpath(p) for p in (protected_paths or []) if isinstance(p, str)}
    if real_target in protected:
        return _result(analysis, STATUS_BLOCKED, file_path=target_file, changes_requested=1,
                       error=f"{target_file!r} is a protected file and is never modified.")

    validation = build_code_correction_proposal_validation(proposal, allowed_dirs=allowed_dirs)
    if validation.get("status") != VALIDATION_STATUS_VALID:
        status = _classify_error_text(validation.get("reason")) or STATUS_INVALID
        return _result(analysis, status, file_path=target_file, changes_requested=1,
                       error=validation.get("reason"), validation_result=validation)

    # Read-only pre-check of the *resulting* source (nothing is written
    # or executed): fragment must be unique and the corrected file must
    # still parse.
    try:
        current = make_text_file_read_handler(allowed_dirs=allowed_dirs)({"path": target_file})["text"]
    except (ValueError, OSError, TypeError) as exc:
        return _result(analysis, _classify_error_text(str(exc)) or STATUS_INVALID,
                       file_path=target_file, changes_requested=1, error=str(exc),
                       validation_result=validation)
    occurrences = current.count(old_text)
    if occurrences != 1:
        return _result(analysis, STATUS_INVALID, file_path=target_file, changes_requested=1,
                       validation_result=validation,
                       error=(f"old_text was not found in {target_file!r}." if occurrences == 0
                              else f"old_text appears {occurrences} times; exactly one is required."))
    inspection = inspect_source(current.replace(old_text, new_text, 1), filename=target_file)
    code_validation = {"valid": inspection["valid"], "syntax_error": inspection["syntax_error"]}
    if not inspection["valid"]:
        return _result(analysis, STATUS_INVALID, file_path=target_file, changes_requested=1,
                       validation_result=validation, code_validation=code_validation,
                       error="The corrected source would not be valid Python; nothing was changed.")

    handler = make_code_change_apply_handler(allowed_dirs=allowed_dirs)
    try:
        outcome = handler({"path": target_file, "old_text": old_text, "new_text": new_text})
    except (ValueError, OSError, TypeError) as exc:
        return _result(analysis, _classify_error_text(str(exc)) or STATUS_FAILED,
                       file_path=target_file, changes_requested=1, error=str(exc),
                       validation_result=validation, code_validation=code_validation)

    metadata = outcome.get("change_metadata")
    if not outcome.get("change_applied"):
        not_ready = outcome.get("success") is False and "occurrences_replaced" not in (metadata or {})
        return _result(analysis, STATUS_INVALID if not_ready else STATUS_FAILED,
                       file_path=outcome.get("path", target_file), changes_requested=1,
                       change_metadata=metadata, validation_result=validation,
                       code_validation=code_validation,
                       error=_validation_metadata_error(metadata))

    return _result(analysis, STATUS_APPLIED, file_path=outcome.get("path", target_file),
                   changes_requested=1, change_metadata=metadata,
                   validation_result=validation, code_validation=code_validation)
