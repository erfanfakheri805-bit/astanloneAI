"""
Controlled Internal Evolution Result Validation (Prompt 907, Section 18)
=======================================================================
One small deterministic validation layer for the Prompt 906 internal evolution result contract.

  validate_internal_evolution_result_context(result, expected_identity=None)

This is descriptive validation only. It never implements, executes, modifies, generates or
authorizes anything, grants no approval or permission, calls no Claude / external AI / API, and
uses no network or filesystem. implementation_allowed, execution_allowed, implementation_started
and executed are ALWAYS False in its output.

The input's own "valid" field is never trusted: validity is re-derived from the actual fields
(real Prompt 906 validator + exact "evaluated" status, stage, result_type, summary and
requirement labels, identity text rules, forbidden-state scan, code-like / external-reference
scan). Evaluation order (first match decides):
   any permission / approval / execution flag truthy (at any depth) ... forbidden_execution_state
   malformed / forged / not "evaluated" / wrong stage or result_type /
     wrong requirements / code-like or external-service content ........ invalid_result
   expected_identity differs from the result identity ................... context_mismatch
   all checks pass ...................................................... valid
   unexpected internal failure .......................................... validation_error

Output (exactly these fifteen keys, a fresh dict per call):
  {"version", "status", "valid", "request_id", "implementation_request_id", "capability_name",
   "operation", "stage", "result_type", "errors", "warnings", "implementation_allowed",
   "execution_allowed", "implementation_started", "executed"}
errors is a list of {"code", "where"} (bounded); warnings is always []. Identity, stage and
result_type are copied only for status "valid" (None otherwise).
"""

import re

from autonomy.claude_exit_readiness import FALSE_FLAGS, IDENTITY_KEYS
from autonomy.internal_evolution_result import (
    REQUIREMENTS_MET, REQUIREMENTS_MISSING, RESULT_KEYS, RESULT_TYPE, STAGE,
    STATUS_EVALUATED, SUMMARY, validate_internal_evolution_result)

RESULT_VERSION = 1

STATUS_VALID = "valid"
STATUS_INVALID = "invalid_result"
STATUS_CONTEXT = "context_mismatch"
STATUS_FORBIDDEN = "forbidden_execution_state"
STATUS_ERROR = "validation_error"

STATUSES = (STATUS_VALID, STATUS_INVALID, STATUS_CONTEXT, STATUS_FORBIDDEN, STATUS_ERROR)

OUTPUT_KEYS = ("version", "status", "valid", "request_id", "implementation_request_id",
               "capability_name", "operation", "stage", "result_type", "errors", "warnings",
               "implementation_allowed", "execution_allowed", "implementation_started",
               "executed")

_FORBIDDEN_KEYS = FALSE_FLAGS + (
    "approved", "approval_granted", "authorized", "authorization_granted",
    "permission_granted", "implementation_approved", "execution_approved")

# code / patch / command / key / URL look-alikes (substring match, lowercase)
_CODE_MARKERS = ("://", "http", "www.", "```", "def ", "class ", "import ", "sudo", "rm -",
                 "curl", "wget", "api_key", "apikey", "secret", "token", "diff --git", "@@",
                 "#!", "exec(", "eval(", "subprocess", "$(", "&&", "||", ";", "|", "<", ">",
                 "{", "}", "\n", "\r", "\t", "`")
# external AI / API / network / service references (whole-word match)
_EXTERNAL_WORDS = frozenset((
    "api", "openai", "anthropic", "claude", "gpt", "llm", "url", "network", "internet",
    "server", "socket", "cloud", "service", "endpoint", "webhook", "remote"))

_MAX_ERRORS = 20
_MAX_SCAN_NODES = 20000
_MAX_SCAN_DEPTH = 12


def _output(status, errors=(), source=None):
    ok = status == STATUS_VALID
    out = {"version": RESULT_VERSION, "status": status, "valid": ok}
    for key in IDENTITY_KEYS:
        out[key] = source[key] if ok else None
    out.update({"stage": STAGE if ok else None, "result_type": RESULT_TYPE if ok else None,
                "errors": [dict(e) for e in errors][:_MAX_ERRORS], "warnings": [],
                "implementation_allowed": False, "execution_allowed": False,
                "implementation_started": False, "executed": False})
    return out


def _forbidden_keys(obj):
    """Names of permission / approval / execution flags set truthy anywhere in obj."""
    found = []
    stack = [(obj, 0)]
    seen = 0
    while stack:
        node, depth = stack.pop()
        seen += 1
        if seen > _MAX_SCAN_NODES or depth > _MAX_SCAN_DEPTH:
            continue
        if type(node) is dict:
            for key, value in node.items():
                if type(key) is str and key in _FORBIDDEN_KEYS:
                    try:
                        truthy = bool(value)
                    except Exception:
                        truthy = True
                    if truthy and key not in found:
                        found.append(key)
                stack.append((value, depth + 1))
        elif type(node) in (list, tuple):
            for value in node:
                stack.append((value, depth + 1))
    return sorted(found)


def _unsafe_text(text):
    low = text.lower()
    if any(marker in low for marker in _CODE_MARKERS):
        return "code_like_content"
    if _EXTERNAL_WORDS.intersection(re.split(r"[^a-z0-9]+", low)):
        return "external_reference"
    return None


def _structural_errors(result):
    errors = []

    def add(code, where):
        if len(errors) < _MAX_ERRORS and {"code": code, "where": where} not in errors:
            errors.append({"code": code, "where": where})

    for error in validate_internal_evolution_result(result)["errors"]:
        add(error["code"], error["where"])
    if type(result) is not dict or any(k not in result for k in RESULT_KEYS) \
            or any(type(k) is not str or k not in RESULT_KEYS for k in result):
        return errors  # shape errors already reported; field diagnostics need the exact shape
    if result["status"] != STATUS_EVALUATED:
        add("result_not_evaluated", "status")
        return errors
    for key, expected in (("requirements_met", REQUIREMENTS_MET),
                          ("requirements_missing", REQUIREMENTS_MISSING)):
        if type(result[key]) is not list or any(type(v) is not str for v in result[key]):
            continue
        for label in expected:
            if label not in result[key]:
                add("requirement_missing", label)
        for label in result[key]:
            if label not in expected:
                add("unexpected_requirement", key)
    for key in IDENTITY_KEYS + ("requirements_met", "requirements_missing"):
        values = result[key] if type(result[key]) is list else [result[key]]
        for text in values:
            problem = _unsafe_text(text) if type(text) is str else None
            if problem:
                add(problem, key)
    if result["summary"] != SUMMARY:
        add("invalid_summary", "summary")
    return errors


def _identity_mismatches(result, expected):
    if type(expected) is not dict:
        return [{"code": "invalid_expected_identity", "where": "expected_identity"}]
    errors = []
    for key in IDENTITY_KEYS:
        if key in expected and (type(expected[key]) is not type(result[key])
                                or expected[key] != result[key]):
            errors.append({"code": "identity_mismatch", "where": key})
    if any(type(k) is not str or k not in IDENTITY_KEYS for k in expected):
        errors.append({"code": "invalid_expected_identity", "where": "expected_identity"})
    return errors


def validate_internal_evolution_result_context(result=None, expected_identity=None):
    """Deterministic validation of a Prompt 906 result (descriptive only; never raises)."""
    try:
        flags = _forbidden_keys(result)
        if flags:
            return _output(STATUS_FORBIDDEN, [{"code": "forbidden_flag", "where": k}
                                              for k in flags])
        errors = _structural_errors(result)
        if errors:
            return _output(STATUS_INVALID, errors)
        if expected_identity is not None:
            mismatches = _identity_mismatches(result, expected_identity)
            if mismatches:
                return _output(STATUS_CONTEXT, mismatches)
        return _output(STATUS_VALID, (), result)
    except Exception:
        return _output(STATUS_ERROR, [{"code": "validation_error", "where": "result"}])
