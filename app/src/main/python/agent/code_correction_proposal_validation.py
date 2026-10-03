"""
Agent - Code Correction Proposal Validation
================================================
Connects the existing code-correction proposal
(agent/code_correction_proposal.py's `build_code_correction_proposal`,
Prompt 341) to one small, structured validation result that decides
whether that proposal is safe to ever apply:

    CodeCorrectionProposal -> build_code_correction_proposal_validation()
        -> {status, target_file, reason, is_safe_to_apply}

Reuses, never duplicates:
  - `agent.code_correction_proposal.STATUS_PROPOSED`/`STATUS_NOT_READY`
    are imported, unchanged, rather than a second, differently-spelled
    "is this proposal ready" vocabulary - this module's own
    `"proposal status is ready for validation"` check (requirement 3)
    is nothing but `proposal["status"] == STATUS_PROPOSED`, and its own
    `VALIDATION_STATUS_NOT_READY` *is*
    `code_correction_proposal.STATUS_NOT_READY` (the identical string),
    so a proposal that was already `NOT_READY` when it was built stays
    reported as `NOT_READY` here too, never silently relabeled.
  - `execution.text_file_read_capability._resolve_allowed_dirs`/
    `_is_within_allowed_dirs` - the exact same safe-directory
    resolution and containment check every file-touching capability in
    this project already uses (`text_file_read`/`text_file_write`/
    `text_file_edit`/`code_analysis`/`code_change_plan` all delegate
    to these same two functions) - are imported, unchanged, to decide
    "target path is allowed" (requirement 3). This module never
    re-implements path-safety logic a second way, and - crucially -
    never needs to: both functions work from `os.path.realpath` alone,
    so this check runs without ever opening, reading, or writing
    `target_file` (requirements 7, 8).

This is a validation step, not a second proposal or correction system
(requirement 9): it never builds a `CodeCorrectionProposal` of its
own, never re-decides *what* the correction should be, and only ever
reads fields the existing proposal (Prompt 341) already computed, plus
the one additional, purely path-based safety fact
(`_is_within_allowed_dirs`) already used everywhere else in this
project. `proposal` itself is only ever read from, never mutated,
copied-with-changes, or reconstructed (requirement 10: "preserve the
original correction proposal unchanged").

`status` (requirement 3, 4) is exactly one of:
    `VALID`     - every one of the five checks below passed.
    `INVALID`   - the proposal claimed to be `PROPOSED` (ready for
                  validation) but is missing required content, or
                  names a `target_file` outside the allowed
                  directories.
    `NOT_READY` - the proposal itself was never `PROPOSED` to begin
                  with (it is `NOT_READY`, or not a real proposal
                  dict at all) - there is nothing here for this
                  module to validate or contradict; it reports the
                  same "not ready" state honestly rather than
                  inventing a verdict about content the proposal
                  never claimed to have settled.

The five checks (requirement 3), in the fixed order they are run and
reported in:
  1. proposal status is ready for validation (`status == PROPOSED`) -
     checked first, since every other check only makes sense once the
     proposal itself claims to be complete.
  2. target file is present (`target_file` is a non-empty string).
  3. error information is present (`error_type` is present).
  4. correction description is present (`change_description` is
     present).
  5. target path is allowed (`_is_within_allowed_dirs`, reused
     unchanged as described above).

Checked in that fixed order, and this function returns as soon as one
fails - `reason` always names exactly the one check that failed,
never a merged, harder-to-read list, same "one concrete reason" shape
`build_code_correction_proposal`'s own `NOT_READY` reasons already
use.

`is_safe_to_apply` (requirement 6) is `True` if and only if `status`
is `VALID` - derived from nothing else, and always `False` for
`INVALID`/`NOT_READY`.

Never modifies, applies, or writes to `target_file` or any other file,
and never executes anything (requirements 7, 8) - the only filesystem
call this module ever makes is `os.path.realpath`, exactly like every
other capability that already reuses `_is_within_allowed_dirs`; no
file is ever opened. Never generates or re-generates a correction
proposal, and never invokes `code_change_plan` or any other capability
- purely a read-only, structural/safety check on top of an
already-built proposal.

Never raises: any input that isn't a real `CodeCorrectionProposal`
dict is reported as `status=NOT_READY`, `is_safe_to_apply=False`, with
an explanatory `reason` - the same "always return a structured,
honest verdict" convention `build_code_correction_proposal` itself
already follows.
"""

import os

from .code_correction_proposal import STATUS_PROPOSED, STATUS_NOT_READY
from execution.text_file_read_capability import _resolve_allowed_dirs, _is_within_allowed_dirs

VALIDATION_STATUS_VALID = "VALID"
VALIDATION_STATUS_INVALID = "INVALID"
# Deliberately the *same* string as code_correction_proposal.STATUS_NOT_READY
# (see module docstring) - imported, not redefined.
VALIDATION_STATUS_NOT_READY = STATUS_NOT_READY

ALL_CODE_CORRECTION_PROPOSAL_VALIDATION_STATUSES = (
    VALIDATION_STATUS_VALID, VALIDATION_STATUS_INVALID, VALIDATION_STATUS_NOT_READY,
)


def build_code_correction_proposal_validation(proposal, allowed_dirs=None):
    """Build the small, structured validation result
    `AgentLoop.validate_code_correction_proposal` (agent/agent_loop.py)
    exposes, on top of - and without duplicating - the existing
    `CodeCorrectionProposal` `proposal` already is.

    Always returns:
        {
            "status": <"VALID"/"INVALID"/"NOT_READY" - see module
                      docstring>,
            "target_file": <proposal["target_file"], or None>,
            "reason": <str naming exactly the one check that failed,
                      or, for VALID, a short confirming message>,
            "is_safe_to_apply": <bool - True only for VALID>,
        }

    `allowed_dirs`, if given, is forwarded unchanged to
    `_resolve_allowed_dirs` (used only by the fifth, path-safety
    check) - same "replace the application's own default safe
    directories entirely" convention every capability that already
    accepts this parameter follows; omitted, the application's real
    default directories are resolved the first time this function
    actually runs, never at import time.

    Never modifies `proposal`, applies it, writes to `target_file`, or
    executes anything - see module docstring. Never raises: a
    malformed `proposal` (not a dict, or missing the fields
    `CodeCorrectionProposal` always carries) is reported as
    `status=NOT_READY`, exactly like a proposal that was already
    `NOT_READY` when it was built."""
    is_dict = isinstance(proposal, dict)
    target_file = proposal.get("target_file") if is_dict else None

    if not is_dict:
        return {
            "status": VALIDATION_STATUS_NOT_READY,
            "target_file": None,
            "reason": "No correction proposal was available to validate.",
            "is_safe_to_apply": False,
        }

    if proposal.get("status") != STATUS_PROPOSED:
        return {
            "status": VALIDATION_STATUS_NOT_READY,
            "target_file": target_file,
            "reason": (
                "The correction proposal is not ready for validation "
                f"(status={proposal.get('status')!r})."
            ),
            "is_safe_to_apply": False,
        }

    if not target_file or not isinstance(target_file, str):
        return {
            "status": VALIDATION_STATUS_INVALID,
            "target_file": target_file,
            "reason": "The proposal does not identify a target file.",
            "is_safe_to_apply": False,
        }

    if not proposal.get("error_type"):
        return {
            "status": VALIDATION_STATUS_INVALID,
            "target_file": target_file,
            "reason": "The proposal does not include error information.",
            "is_safe_to_apply": False,
        }

    if not proposal.get("change_description"):
        return {
            "status": VALIDATION_STATUS_INVALID,
            "target_file": target_file,
            "reason": "The proposal does not include a correction description.",
            "is_safe_to_apply": False,
        }

    resolved_allowed_dirs = _resolve_allowed_dirs(allowed_dirs)
    real_path = os.path.realpath(target_file)
    if not _is_within_allowed_dirs(real_path, resolved_allowed_dirs):
        return {
            "status": VALIDATION_STATUS_INVALID,
            "target_file": target_file,
            "reason": f"Target path {target_file!r} is outside the allowed directories.",
            "is_safe_to_apply": False,
        }

    return {
        "status": VALIDATION_STATUS_VALID,
        "target_file": target_file,
        "reason": f"Correction proposal for {target_file!r} is valid and safe to apply.",
        "is_safe_to_apply": True,
    }
