"""
Reasoning - reasoning-to-capability boundary checkpoint (Prompt 840)
====================================================================
The final small checkpoint of the Reasoning & Planning foundation. It
accepts a reasoning decision (Prompt 837) and an optional capability spec
and produces ONE stable boundary result that says where the request goes
next. It reuses the Prompt 839 integration and classifier; it contains no
contract, spec or decision logic of its own.

  evaluate_reasoning_capability_boundary(decision, spec=None,
                                         integrator=integrate_capability_contract)

`integrator` defaults to the existing Prompt 839 integration and is only a
seam so the boundary can be exercised against a faulty integration.

Result (always the same keys, in this order, JSON-safe):

  {"version", "decision_state", "capability_classification",
   "contract_valid", "execution_allowed", "next_stage", "reason",
   "executed"}

  decision_state            "ready" | "needs_clarification" |
                            "needs_information" | "invalid" (the decision
                            is unusable or an invalid plan) | "unknown"
                            (the integration result itself was unusable)
  capability_classification the Prompt 839 outcome: "decision_not_ready" |
                            "spec_missing" | "spec_invalid" |
                            "contract_valid" | "integration_error"
  contract_valid            True only when a validated contract exists
  execution_allowed         always False
  next_stage                "clarify" | "request_information" |
                            "capability_definition" | "capability_system"
  reason                    the Prompt 838 build reason ("built",
                            "needs_clarification", "decision_invalid",
                            "capability_unspecified", "missing_field", ...);
                            "boundary_error" in the safe result
  executed                  always False

Mapping (by classification, then decision state):

  decision_not_ready, needs_clarification  -> clarify
  decision_not_ready, needs_information    -> request_information
  decision_not_ready, invalid              -> request_information
  spec_missing                             -> capability_definition
  spec_invalid                             -> capability_definition
  integration_error                        -> capability_definition
  contract_valid                           -> capability_system

"capability_system" is reached only when a valid capability contract exists
(contract_valid is True); any result that would break that is replaced by
the safe result {decision_state "unknown", classification
"integration_error", contract_valid False, next_stage
"capability_definition"}.

Nothing is executed, registered, installed, repaired, modified or invented:
the boundary only describes the next stage and never supplies a capability
name, tool, handler or implementation detail, and it does not carry the
contract itself. Bounded (the integration bounds its work), JSON-safe,
deterministic, always a fresh dict, never raises. Pure stdlib; no Memory,
AEL, Core, NLU change, registry, execution, LLM or network.
"""

from .capability_integration import (
    integrate_capability_contract, classify_capability_result,
    OUTCOME_DECISION_NOT_READY, OUTCOME_SPEC_MISSING, OUTCOME_SPEC_INVALID,
    OUTCOME_CONTRACT_VALID, OUTCOME_INTEGRATION_ERROR,
)

BOUNDARY_VERSION = 1

STATE_READY = "ready"
STATE_NEEDS_CLARIFICATION = "needs_clarification"
STATE_NEEDS_INFORMATION = "needs_information"
STATE_INVALID = "invalid"
STATE_UNKNOWN = "unknown"

STAGE_CLARIFY = "clarify"
STAGE_REQUEST_INFORMATION = "request_information"
STAGE_CAPABILITY_DEFINITION = "capability_definition"
STAGE_CAPABILITY_SYSTEM = "capability_system"

NEXT_STAGES = (STAGE_CLARIFY, STAGE_REQUEST_INFORMATION,
               STAGE_CAPABILITY_DEFINITION, STAGE_CAPABILITY_SYSTEM)
DECISION_STATES = (STATE_READY, STATE_NEEDS_CLARIFICATION, STATE_NEEDS_INFORMATION,
                   STATE_INVALID, STATE_UNKNOWN)
CLASSIFICATIONS = (OUTCOME_DECISION_NOT_READY, OUTCOME_SPEC_MISSING, OUTCOME_SPEC_INVALID,
                   OUTCOME_CONTRACT_VALID, OUTCOME_INTEGRATION_ERROR)

REASON_BOUNDARY_ERROR = "boundary_error"

_REASON_MAX = 64


def _result(state, classification, contract_valid, stage, reason):
    return {"version": BOUNDARY_VERSION, "decision_state": state,
            "capability_classification": classification,
            "contract_valid": contract_valid, "execution_allowed": False,
            "next_stage": stage, "reason": reason, "executed": False}


def _safe(reason=REASON_BOUNDARY_ERROR):
    return _result(STATE_UNKNOWN, OUTCOME_INTEGRATION_ERROR, False,
                   STAGE_CAPABILITY_DEFINITION, reason)


def _decision_state(classification, integration):
    """Decision state, read from the integration result (no decision logic here)."""
    if classification == OUTCOME_INTEGRATION_ERROR:
        return STATE_UNKNOWN
    if classification == OUTCOME_DECISION_NOT_READY:
        if integration["reason"] == STATE_NEEDS_CLARIFICATION:
            return STATE_NEEDS_CLARIFICATION
        if integration["reason"] == STATE_NEEDS_INFORMATION:
            return STATE_NEEDS_INFORMATION
        return STATE_INVALID
    return STATE_READY


def _next_stage(classification, state):
    if classification == OUTCOME_CONTRACT_VALID:
        return STAGE_CAPABILITY_SYSTEM
    if classification == OUTCOME_DECISION_NOT_READY:
        return STAGE_CLARIFY if state == STATE_NEEDS_CLARIFICATION else STAGE_REQUEST_INFORMATION
    return STAGE_CAPABILITY_DEFINITION


def evaluate_reasoning_capability_boundary(decision, spec=None,
                                           integrator=integrate_capability_contract):
    """Boundary result for `decision` and optional `spec` (see module
    docstring). Read-only; never raises."""
    try:
        try:
            integration = integrator(decision, spec)
        except Exception:
            return _safe()
        classification = classify_capability_result(integration)
        if classification not in CLASSIFICATIONS or classification == OUTCOME_INTEGRATION_ERROR:
            return _safe()
        reason = integration["reason"]
        if not isinstance(reason, str) or not reason or len(reason) > _REASON_MAX:
            return _safe()
        state = _decision_state(classification, integration)
        stage = _next_stage(classification, state)
        contract_valid = classification == OUTCOME_CONTRACT_VALID
        if (state not in DECISION_STATES or stage not in NEXT_STAGES
                or (stage == STAGE_CAPABILITY_SYSTEM) != contract_valid):
            return _safe()
        return _result(state, classification, contract_valid, stage, reason)
    except Exception:  # pragma: no cover - defensive
        return _safe()
