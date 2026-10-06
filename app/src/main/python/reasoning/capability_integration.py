"""
Reasoning - capability contract integration checkpoint (Prompt 839)
===================================================================
One small read-only layer that connects the validated reasoning decision
(Prompt 837, `reasoning.reasoning_decision.decide_reasoning`) to the
existing capability contract foundation (Prompt 838,
`reasoning.capability_contract`).

  integrate_capability_contract(decision, spec=None, builder=build_capability_contract)
  classify_capability_result(result)

`integrate_capability_contract` returns the EXISTING Prompt 838 build result
unchanged ({"version", "status", "reason", "contract", "validation",
"executed"}): the contract behaviour and validation rules are exactly those
of `build_capability_contract`; nothing is added to, removed from or
reworded in that result. `builder` defaults to the existing builder and is
only a seam so the integration can be exercised against a faulty builder.

The integration only re-checks what it is handed before returning it. A
result that is not a well-formed build result, that claims execution, or
whose "built" contract does not pass `validate_capability_contract` with
execution_allowed False, is never passed on: it is replaced by

  {"version", "status": "invalid", "reason": "integration_result_invalid",
   "contract": None, "validation": None, "executed": False}

(the real builder never produces this).

`classify_capability_result(result)` names the outcome of such a result,
so the four situations are never confused:

  "decision_not_ready"  the decision is not usable or not ready: status
                        "unknown" with reason "decision_invalid", or
                        "insufficient" (needs clarification / information)
  "spec_missing"        the decision is ready but the spec is missing or
                        insufficient: "unknown"/"capability_unspecified" or
                        "incomplete" (required fields absent)
  "spec_invalid"        the spec is present but malformed: "invalid" (any
                        reason other than integration_result_invalid)
  "contract_valid"      "built": a validated contract with
                        execution_allowed False
  "integration_error"   anything else (including a replaced faulty result)

Nothing is executed, registered, installed, repaired, modified or invented:
no capability name, tool, implementation or handler is ever supplied by
this layer; the decision and spec are only read. Bounded (the builder
bounds its work), JSON-safe, deterministic, always a fresh result, never
raises. Pure stdlib; no Memory, AEL, Core, NLU change, registry,
execution, LLM or network.
"""

import copy

from .capability_contract import (
    build_capability_contract, validate_capability_contract, BUILD_VERSION,
    BUILD_BUILT, BUILD_UNKNOWN, BUILD_INSUFFICIENT, BUILD_INCOMPLETE, BUILD_INVALID,
    REASON_DECISION_INVALID, REASON_CAPABILITY_UNSPECIFIED, _CONTRACT_FIELDS,
)

INTEGRATION_VERSION = 1

OUTCOME_DECISION_NOT_READY = "decision_not_ready"
OUTCOME_SPEC_MISSING = "spec_missing"
OUTCOME_SPEC_INVALID = "spec_invalid"
OUTCOME_CONTRACT_VALID = "contract_valid"
OUTCOME_INTEGRATION_ERROR = "integration_error"

REASON_INTEGRATION_RESULT_INVALID = "integration_result_invalid"

_RESULT_KEYS = ("version", "status", "reason", "contract", "validation", "executed")
_STATUSES = (BUILD_BUILT, BUILD_UNKNOWN, BUILD_INSUFFICIENT, BUILD_INCOMPLETE, BUILD_INVALID)


def _fallback():
    return {"version": BUILD_VERSION, "status": BUILD_INVALID,
            "reason": REASON_INTEGRATION_RESULT_INVALID, "contract": None,
            "validation": None, "executed": False}


def _well_formed(result):
    """True only for a build result that is safe to hand on."""
    if not isinstance(result, dict) or list(result) != list(_RESULT_KEYS):
        return False
    if result["version"] != BUILD_VERSION or isinstance(result["version"], bool):
        return False
    if result["status"] not in _STATUSES or not isinstance(result["reason"], str):
        return False
    if result["executed"] is not False:
        return False
    contract = result["contract"]
    if result["status"] == BUILD_BUILT:
        if not isinstance(contract, dict) or list(contract) != list(_CONTRACT_FIELDS):
            return False
        if contract["execution_allowed"] is not False:
            return False
        return validate_capability_contract(contract)["valid"] is True
    return contract is None


def integrate_capability_contract(decision, spec=None, builder=build_capability_contract):
    """Prompt 838 build result for a Prompt 837 `decision` and an explicit
    capability `spec` (see module docstring). Read-only; never raises."""
    try:
        try:
            result = builder(decision, spec)
        except Exception:
            return _fallback()
        if not _well_formed(result):
            return _fallback()
        return copy.deepcopy(result)
    except Exception:  # pragma: no cover - defensive
        return _fallback()


def classify_capability_result(result):
    """Outcome name for a build result (see module docstring). Never raises."""
    try:
        if not _well_formed(result):
            return OUTCOME_INTEGRATION_ERROR
        status, reason = result["status"], result["reason"]
        if status == BUILD_BUILT:
            return OUTCOME_CONTRACT_VALID
        if status == BUILD_INSUFFICIENT:
            return OUTCOME_DECISION_NOT_READY
        if status == BUILD_UNKNOWN:
            if reason == REASON_DECISION_INVALID:
                return OUTCOME_DECISION_NOT_READY
            if reason == REASON_CAPABILITY_UNSPECIFIED:
                return OUTCOME_SPEC_MISSING
            return OUTCOME_INTEGRATION_ERROR
        if status == BUILD_INCOMPLETE:
            return OUTCOME_SPEC_MISSING
        if status == BUILD_INVALID and reason != REASON_INTEGRATION_RESULT_INVALID:
            return OUTCOME_SPEC_INVALID
        return OUTCOME_INTEGRATION_ERROR
    except Exception:  # pragma: no cover - defensive
        return OUTCOME_INTEGRATION_ERROR
