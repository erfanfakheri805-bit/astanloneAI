"""
Final Controlled Internal Evolution Gate (Prompt 908, Section 18)
================================================================
One small deterministic, DESCRIPTIVE gate that evaluates whether a Prompt 907 validation result is
structurally sufficient to leave the Claude-dependent architecture path and enter the final
autonomy-validation checkpoint.

  build_final_internal_evolution_gate(validation_result, expected_identity=None)

It implements, executes, modifies, generates and authorizes nothing, grants no approval or
permission, calls no Claude / external AI / API and uses no network or filesystem.
implementation_allowed, execution_allowed, implementation_started and executed are ALWAYS False.
"ready_for_final_autonomy_validation" only means the structural description is sufficient; it is
not a permission and the three requirements_missing labels remain outstanding.

The supplied Prompt 907 result is never trusted (its "valid" field included). It is re-derived:
the exact fifteen-key shape and field values are checked, and the identity is re-validated by
rebuilding the descriptive Prompt 906 result and running the real Prompt 907 validator on it.
Evaluation order (first match decides):
   any permission / approval / execution flag truthy (at any depth) ... forbidden_execution_state
   malformed / forged / invalid / wrong status, stage or result_type /
     errors or warnings present / code-like or external-service text ... invalid_validation_result
   expected_identity differs from the validation identity .............. context_mismatch
   all checks pass ...................................................... ready_for_final_autonomy_validation
   unexpected internal failure .......................................... gate_error

Result (exactly these sixteen keys, a fresh dict per call, primitive values / lists of str only):
  {"version", "status", "valid", "request_id", "implementation_request_id", "capability_name",
   "operation", "stage", "gate", "summary", "requirements_met", "requirements_missing",
   "implementation_allowed", "execution_allowed", "implementation_started", "executed"}
valid is True only when ready. Only then are identity, stage, gate, summary and the two
requirement lists populated; otherwise those are None / empty lists.
"""

import re

from autonomy.claude_exit_readiness import FALSE_FLAGS, IDENTITY_KEYS
from autonomy.internal_evolution_result import (
    REQUIREMENTS_MET as RESULT_MET, REQUIREMENTS_MISSING as RESULT_MISSING, RESULT_TYPE, STAGE,
    STATUS_EVALUATED, SUMMARY as RESULT_SUMMARY)
from autonomy.internal_evolution_result_validation import (
    OUTPUT_KEYS as VALIDATION_KEYS, RESULT_VERSION as VALIDATION_VERSION,
    STATUS_VALID as VALIDATION_VALID, validate_internal_evolution_result_context)

GATE_VERSION = 1

STATUS_READY = "ready_for_final_autonomy_validation"
STATUS_INVALID = "invalid_validation_result"
STATUS_CONTEXT = "context_mismatch"
STATUS_FORBIDDEN = "forbidden_execution_state"
STATUS_ERROR = "gate_error"

STATUSES = (STATUS_READY, STATUS_INVALID, STATUS_CONTEXT, STATUS_FORBIDDEN, STATUS_ERROR)

GATE = "final_internal_evolution_gate"
SUMMARY = ("Descriptive final gate over the validated internal evolution result only; "
           "nothing was implemented, approved or executed.")
REQUIREMENTS_MET = ("prompt907_validation_valid", "stage_correct", "result_type_descriptive",
                    "identity_context_consistent", "execution_constraints_preserved")
REQUIREMENTS_MISSING = ("implementation_permission", "execution_permission",
                        "final_autonomy_validation")

OUTPUT_KEYS = ("version", "status", "valid", "request_id", "implementation_request_id",
               "capability_name", "operation", "stage", "gate", "summary", "requirements_met",
               "requirements_missing", "implementation_allowed", "execution_allowed",
               "implementation_started", "executed")

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

_MAX_SCAN_NODES = 20000
_MAX_SCAN_DEPTH = 12


def _output(status, source=None):
    ok = status == STATUS_READY
    out = {"version": GATE_VERSION, "status": status, "valid": ok}
    for key in IDENTITY_KEYS:
        out[key] = source[key] if ok else None
    out.update({"stage": STAGE if ok else None, "gate": GATE if ok else None,
                "summary": SUMMARY if ok else None,
                "requirements_met": list(REQUIREMENTS_MET) if ok else [],
                "requirements_missing": list(REQUIREMENTS_MISSING) if ok else [],
                "implementation_allowed": False, "execution_allowed": False,
                "implementation_started": False, "executed": False})
    return out


def _forbidden_state(obj):
    """True if any dict (at any depth) sets a permission / approval / execution flag."""
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
                        if bool(value):
                            return True
                    except Exception:
                        return True
                stack.append((value, depth + 1))
        elif type(node) in (list, tuple):
            for value in node:
                stack.append((value, depth + 1))
    return False


def _unsafe_text(text):
    low = text.lower()
    if any(marker in low for marker in _CODE_MARKERS):
        return True
    return bool(_EXTERNAL_WORDS.intersection(re.split(r"[^a-z0-9]+", low)))


def _exact_keys(result):
    return type(result) is dict and len(result) == len(VALIDATION_KEYS) \
        and all(type(k) is str for k in result) and all(k in result for k in VALIDATION_KEYS)


def _shape_ok(result):
    """Exact Prompt 907 valid-result shape, derived from the fields (valid is not trusted)."""
    if not _exact_keys(result):
        return False
    if type(result["version"]) is not int or result["version"] != VALIDATION_VERSION:
        return False
    if type(result["status"]) is not str or result["status"] != VALIDATION_VALID:
        return False
    if result["valid"] is not True:
        return False
    for key, expected in (("stage", STAGE), ("result_type", RESULT_TYPE)):
        if type(result[key]) is not str or result[key] != expected:
            return False
    if type(result["errors"]) is not list or result["errors"]:
        return False
    if type(result["warnings"]) is not list or result["warnings"]:
        return False
    if any(result[key] is not False for key in FALSE_FLAGS):
        return False
    return all(type(result[key]) is str and result[key] and not _unsafe_text(result[key])
               for key in IDENTITY_KEYS)


def _revalidates(result):
    """Rebuild the descriptive Prompt 906 result and run the real Prompt 907 validator on it."""
    rebuilt = {"version": 1, "status": STATUS_EVALUATED, "valid": True}
    for key in IDENTITY_KEYS:
        rebuilt[key] = result[key]
    rebuilt.update({"stage": STAGE, "result_type": RESULT_TYPE, "summary": RESULT_SUMMARY,
                    "requirements_met": list(RESULT_MET),
                    "requirements_missing": list(RESULT_MISSING),
                    **dict.fromkeys(FALSE_FLAGS, False)})
    again = validate_internal_evolution_result_context(rebuilt)
    return again["valid"] is True and again["status"] == VALIDATION_VALID \
        and all(again[key] == result[key] for key in IDENTITY_KEYS)


def _identity_differs(result, expected):
    if type(expected) is not dict:
        return True
    for key in IDENTITY_KEYS:
        if key in expected and (type(expected[key]) is not type(result[key])
                                or expected[key] != result[key]):
            return True
    return any(type(k) is not str or k not in IDENTITY_KEYS for k in expected)


def build_final_internal_evolution_gate(validation_result=None, expected_identity=None):
    """Descriptive final gate for a Prompt 907 validation result (never raises)."""
    try:
        if _forbidden_state(validation_result):
            return _output(STATUS_FORBIDDEN)
        if not _shape_ok(validation_result) or not _revalidates(validation_result):
            return _output(STATUS_INVALID)
        if expected_identity is not None and _identity_differs(validation_result,
                                                               expected_identity):
            return _output(STATUS_CONTEXT)
        return _output(STATUS_READY, validation_result)
    except Exception:
        return _output(STATUS_ERROR)
