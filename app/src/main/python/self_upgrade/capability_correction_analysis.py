"""
Self-Upgrade - Capability Correction Analysis
==============================================
`build_capability_correction_analysis` connects a
`CapabilityEvaluationResult` (self_upgrade.capability_evaluation,
Prompt 366) to the project's EXISTING failure-to-correction pipeline -
it adds no second error analyzer, proposal builder, or validator:

    CapabilityEvaluationResult
        -> (NEEDS_CORRECTION only) execute_generated_code-shaped input
        -> agent.code_error_analysis.build_code_error_analysis
        -> agent.code_correction_proposal.build_code_correction_proposal
        -> agent.code_correction_proposal_validation.
           build_code_correction_proposal_validation
        -> {capability_name, evaluation_status, status, error_analysis,
            correction_proposal, validation, correction_required,
            blockers, errors, failure_info, evaluation_result}

Reuses, unchanged: `build_code_error_analysis`,
`build_code_correction_proposal`, `build_code_correction_proposal_
validation` (called exactly as `AgentLoop.propose_code_correction` /
`validate_code_correction_proposal` call them). The only new logic is
the small adapter that reshapes the failure information the evaluation
already carries into the `execute_generated_code` result shape
(`status/target_file/stdout/stderr/error`) that `build_code_error_
analysis` already accepts: `errors` (joined; `output` if there are
none) -> `stderr`, `output` -> `stdout`, `file_path` -> `target_file`,
`failure_reason` -> `error`. Nothing is invented: no source text is
read or fabricated (`failure_info["source_info"]` only carries what the
evaluation itself holds - the file path).

Status (`status`):
    READY_FOR_CORRECTION  - NEEDS_CORRECTION, the existing analysis
                            was actionable, a proposal was PROPOSED and
                            the existing validation returned VALID.
    NO_CORRECTION_REQUIRED- evaluation SUCCESS.
    BLOCKED               - evaluation BLOCKED or TIMEOUT (never treated
                            as an ordinary code error; `evaluation_status`
                            preserves which), or NEEDS_CORRECTION where
                            the existing analysis/proposal/validation
                            could not honestly proceed (`blockers` says
                            why - e.g. an error type the existing
                            analysis doesn't recognize as actionable).
    INVALID               - evaluation INVALID, or not a well-formed
                            CapabilityEvaluationResult.
    FAILED                - evaluation FAILED (no usable failure
                            information to analyze), or an unexpected
                            exception inside this integration.

`correction_required` mirrors the evaluation's own NEEDS_CORRECTION
verdict (True only for it) - a timeout/blocked/invalid result needs a
different input, not a code correction, so it is False here.

`line_number` caveat: a unittest traceback's last frame usually points
into the *test* file, not the capability file. When the last
`File "...", line N` frame in the failure text is not `file_path`, the
line number is dropped (set to None) from the analysis handed to the
proposal step, so a proposal never cites a wrong line in the capability.

Read-only by construction: never modifies files, executes code,
applies a correction, retries, or activates/registers anything; the
input is never mutated. Never raises.
"""

import copy
import os
import re

from agent.code_error_analysis import build_code_error_analysis
from agent.code_correction_proposal import (
    build_code_correction_proposal,
    STATUS_PROPOSED,
)
from agent.code_correction_proposal_validation import (
    build_code_correction_proposal_validation,
    VALIDATION_STATUS_VALID,
)
from code_generation.generated_code_execution import STATUS_FAILED as EXECUTION_STATUS_FAILED
from self_upgrade.capability_evaluation import (
    EVAL_SUCCESS, EVAL_FAILED, EVAL_TIMEOUT, EVAL_BLOCKED, EVAL_INVALID,
    EVAL_NEEDS_CORRECTION, ALL_EVALUATION_STATUSES,
)

STATUS_READY_FOR_CORRECTION = "READY_FOR_CORRECTION"
STATUS_NO_CORRECTION_REQUIRED = "NO_CORRECTION_REQUIRED"
STATUS_BLOCKED = "BLOCKED"
STATUS_INVALID = "INVALID"
STATUS_FAILED = "FAILED"

ALL_STATUSES = (
    STATUS_READY_FOR_CORRECTION, STATUS_NO_CORRECTION_REQUIRED,
    STATUS_BLOCKED, STATUS_INVALID, STATUS_FAILED,
)

_EVALUATION_KEYS = (
    "capability_name", "evaluation_status", "success", "failure_reason",
    "errors", "correction_required", "file_path",
)
_FRAME_RE = re.compile(r'File\s+"([^"]*)",\s+line\s+\d+')


def _non_blank(value):
    return isinstance(value, str) and bool(value.strip())


def _result(evaluation, status, blockers=None, error_analysis=None,
            correction_proposal=None, validation=None, failure_info=None,
            evaluation_status=None, capability_name=None):
    is_dict = isinstance(evaluation, dict)
    if capability_name is None and is_dict:
        capability_name = evaluation.get("capability_name")
    if evaluation_status is None and is_dict:
        evaluation_status = evaluation.get("evaluation_status")
    errors = evaluation.get("errors") if is_dict else None
    try:
        original = copy.deepcopy(evaluation)
    except Exception:
        original = None
    return {
        "capability_name": capability_name,
        "evaluation_status": evaluation_status,
        "status": status,
        "error_analysis": error_analysis,
        "correction_proposal": correction_proposal,
        "validation": validation,
        "correction_required": bool(is_dict and evaluation_status == EVAL_NEEDS_CORRECTION),
        "blockers": list(blockers or []),
        "errors": list(errors) if isinstance(errors, list) else [],
        "failure_info": failure_info,
        "evaluation_result": original,
    }


def _malformed_reason(evaluation):
    if not isinstance(evaluation, dict):
        return "evaluation_result must be a CapabilityEvaluationResult dict."
    if any(key not in evaluation for key in _EVALUATION_KEYS):
        return "evaluation_result is missing expected CapabilityEvaluationResult keys."
    if evaluation["evaluation_status"] not in ALL_EVALUATION_STATUSES:
        return f"Unrecognized evaluation_status: {evaluation['evaluation_status']!r}."
    if not isinstance(evaluation["errors"], list):
        return "evaluation_result errors must be a list."
    if evaluation["evaluation_status"] == EVAL_NEEDS_CORRECTION:
        if not _non_blank(evaluation["capability_name"]):
            return "NEEDS_CORRECTION result has no capability_name."
        if not _non_blank(evaluation["file_path"]):
            return "NEEDS_CORRECTION result has no file_path."
        if evaluation["success"]:
            return "NEEDS_CORRECTION result is inconsistently marked success."
    return None


def _extract_failure_info(evaluation):
    return {
        "capability_name": evaluation["capability_name"],
        "file_path": evaluation["file_path"],
        "tests_failed": evaluation.get("tests_failed"),
        "errors": list(evaluation["errors"]),
        "output": evaluation.get("output"),
        "failure_reason": evaluation.get("failure_reason"),
        # Only what the evaluation itself holds - no source text is read
        # or invented here.
        "source_info": {"file_path": evaluation["file_path"], "source_text": None},
    }


def _to_execution_result(failure_info):
    """Reshape the failure information into the exact
    `execute_generated_code` result shape `build_code_error_analysis`
    already accepts."""
    stderr = "\n".join(e for e in failure_info["errors"] if isinstance(e, str)).strip()
    output = failure_info["output"] if isinstance(failure_info["output"], str) else ""
    return {
        "status": EXECUTION_STATUS_FAILED,
        "target_file": failure_info["file_path"],
        "stdout": output,
        "stderr": stderr or output,
        "error": failure_info["failure_reason"],
    }


def _drop_foreign_line_number(error_analysis, file_path):
    """See module docstring's line_number caveat."""
    stderr = error_analysis.get("stderr") or ""
    frames = _FRAME_RE.findall(stderr)
    if not frames or error_analysis.get("line_number") is None:
        return error_analysis
    last = frames[-1]
    if os.path.realpath(last) == os.path.realpath(file_path):
        return error_analysis
    adjusted = dict(error_analysis)
    adjusted["line_number"] = None
    return adjusted


def build_capability_correction_analysis(
    evaluation_result, allowed_dirs=None, learned_patterns_provider=None,
):
    """Analyze a `CapabilityEvaluationResult` through the existing
    error-analysis / correction-proposal / proposal-validation
    pipeline. See module docstring for statuses and safety rules.

    `allowed_dirs` is forwarded unchanged to the existing proposal
    validation (its own default applies when omitted).
    `learned_patterns_provider`, if given, is a callable
    `error_type -> list` (e.g. `AgentLoop.retrieve_successful_
    correction_patterns`) whose result is passed to the existing
    proposal builder as advisory context only. Never raises."""
    try:
        return _analyze(evaluation_result, allowed_dirs, learned_patterns_provider)
    except Exception as exc:  # pragma: no cover - defensive
        return _result(
            evaluation_result if isinstance(evaluation_result, dict) else None,
            STATUS_FAILED,
            blockers=[f"Unexpected error during correction analysis: {type(exc).__name__}: {exc}"],
        )


def _analyze(evaluation, allowed_dirs, learned_patterns_provider):
    problem = _malformed_reason(evaluation)
    if problem is not None:
        return _result(evaluation, STATUS_INVALID, blockers=[problem])

    evaluation_status = evaluation["evaluation_status"]

    if evaluation_status == EVAL_SUCCESS:
        return _result(evaluation, STATUS_NO_CORRECTION_REQUIRED)

    if evaluation_status == EVAL_INVALID:
        return _result(evaluation, STATUS_INVALID, blockers=[
            evaluation.get("failure_reason") or "The capability evaluation was INVALID."])

    if evaluation_status in (EVAL_BLOCKED, EVAL_TIMEOUT):
        return _result(evaluation, STATUS_BLOCKED, blockers=[
            evaluation.get("failure_reason")
            or f"The capability evaluation was {evaluation_status}; it is not an ordinary code error."])

    if evaluation_status == EVAL_FAILED:
        return _result(evaluation, STATUS_FAILED, blockers=[
            evaluation.get("failure_reason")
            or "The capability tests failed with no usable failure information."])

    # EVAL_NEEDS_CORRECTION from here on.
    failure_info = _extract_failure_info(evaluation)
    error_analysis = build_code_error_analysis(_to_execution_result(failure_info))
    error_analysis = _drop_foreign_line_number(error_analysis, failure_info["file_path"])

    learned_patterns = None
    if callable(learned_patterns_provider):
        learned_patterns = learned_patterns_provider(error_analysis.get("error_type"))
    proposal = build_code_correction_proposal(error_analysis, learned_patterns=learned_patterns)

    if proposal.get("status") != STATUS_PROPOSED:
        return _result(
            evaluation, STATUS_BLOCKED, blockers=[proposal.get("reason")],
            error_analysis=error_analysis, correction_proposal=proposal,
            failure_info=failure_info,
        )

    validation = build_code_correction_proposal_validation(proposal, allowed_dirs=allowed_dirs)
    if validation.get("status") != VALIDATION_STATUS_VALID:
        return _result(
            evaluation, STATUS_BLOCKED, blockers=[validation.get("reason")],
            error_analysis=error_analysis, correction_proposal=proposal,
            validation=validation, failure_info=failure_info,
        )

    return _result(
        evaluation, STATUS_READY_FOR_CORRECTION,
        error_analysis=error_analysis, correction_proposal=proposal,
        validation=validation, failure_info=failure_info,
    )
