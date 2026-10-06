"""
Runtime growth - Runtime Growth Proposal Validation (Prompt 944)
=================================================================
`validate_runtime_growth_proposal(proposal)` is a pure, deterministic check that a
value has the exact shape and values of a proposal produced by
`build_runtime_growth_proposal()` (Prompt 943). It returns a fresh dict with only
available, status, valid, error_count and errors:

  - "valid"       exactly the twelve proposal fields; version "1"; available
                  True; status "proposed"; a known proposal_type whose
                  change_scope is the exact mapped value; non-empty string
                  request_id; string target / goal / reason; non-empty list of
                  string plan_steps; execution_allowed False; descriptive_only
                  True;
  - "invalid"     a dict failing any check (available True); `errors` lists
                  stable codes in a fixed order and error_count == len(errors);
  - "unavailable" the input is not a dict, or reading it raised (available False,
                  no errors).

The proposal is never mutated or repaired. Nothing is executed, approved,
applied, read from or written to disk / memory.db / network, and nothing raises.
Not wired into Core, RuntimeCore, AEL, Android, capabilities, upgrades or
Section 18.
"""

from runtime_growth import runtime_growth_proposal as _proposal

STATUS_VALID = "valid"
STATUS_INVALID = "invalid"
STATUS_UNAVAILABLE = "unavailable"

PROPOSAL_TYPE_SCOPES = {
    "capability_creation": "capability_definition_and_implementation_design",
    "capability_improvement": "existing_capability_improvement_design",
    "runtime_improvement": "bounded_runtime_change_design",
}

ERR_MISSING_PREFIX = "missing_"
ERR_UNEXPECTED_FIELD = "unexpected_field"
ERR_INVALID_VERSION = "invalid_version"
ERR_INVALID_AVAILABLE = "invalid_available"
ERR_INVALID_STATUS = "invalid_status"
ERR_INVALID_PROPOSAL_TYPE = "invalid_proposal_type"
ERR_INVALID_REQUEST_ID = "invalid_request_id"
ERR_INVALID_TARGET = "invalid_target"
ERR_INVALID_GOAL = "invalid_goal"
ERR_INVALID_REASON = "invalid_reason"
ERR_INVALID_PLAN_STEPS = "invalid_plan_steps"
ERR_INVALID_CHANGE_SCOPE = "invalid_change_scope"
ERR_SCOPE_TYPE_MISMATCH = "change_scope_type_mismatch"
ERR_INVALID_EXECUTION_ALLOWED = "invalid_execution_allowed"
ERR_INVALID_DESCRIPTIVE_ONLY = "invalid_descriptive_only"


def _result(status, errors):
    return {"available": status != STATUS_UNAVAILABLE, "status": status,
            "valid": status == STATUS_VALID, "error_count": len(errors), "errors": list(errors)}


def _is_str(value):
    return isinstance(value, str)


def validate_runtime_growth_proposal(proposal):
    """See the module docstring. Always returns a fresh dict; never raises."""
    try:
        if not isinstance(proposal, dict):
            return _result(STATUS_UNAVAILABLE, [])
        fields = _proposal.FIELDS
        errors = [ERR_MISSING_PREFIX + name for name in fields if name not in proposal]
        if any(key not in fields for key in proposal):
            errors.append(ERR_UNEXPECTED_FIELD)
        p = {name: proposal[name] for name in fields if name in proposal}

        if "version" in p and not (_is_str(p["version"]) and p["version"] == "1"):
            errors.append(ERR_INVALID_VERSION)
        if "available" in p and p["available"] is not True:
            errors.append(ERR_INVALID_AVAILABLE)
        if "status" in p and not (_is_str(p["status"]) and p["status"] == _proposal.STATUS_PROPOSED):
            errors.append(ERR_INVALID_STATUS)
        type_ok = "proposal_type" in p and _is_str(p["proposal_type"]) \
            and p["proposal_type"] in PROPOSAL_TYPE_SCOPES
        if "proposal_type" in p and not type_ok:
            errors.append(ERR_INVALID_PROPOSAL_TYPE)
        if "request_id" in p and not (_is_str(p["request_id"]) and p["request_id"] != ""):
            errors.append(ERR_INVALID_REQUEST_ID)
        for name, code in (("target", ERR_INVALID_TARGET), ("goal", ERR_INVALID_GOAL),
                           ("reason", ERR_INVALID_REASON)):
            if name in p and not _is_str(p[name]):
                errors.append(code)
        if "plan_steps" in p:
            steps = p["plan_steps"]
            if not (isinstance(steps, list) and len(steps) > 0
                    and all(_is_str(step) for step in steps)):
                errors.append(ERR_INVALID_PLAN_STEPS)
        scope_ok = "change_scope" in p and _is_str(p["change_scope"]) \
            and p["change_scope"] in PROPOSAL_TYPE_SCOPES.values()
        if "change_scope" in p and not scope_ok:
            errors.append(ERR_INVALID_CHANGE_SCOPE)
        if type_ok and scope_ok and PROPOSAL_TYPE_SCOPES[p["proposal_type"]] != p["change_scope"]:
            errors.append(ERR_SCOPE_TYPE_MISMATCH)
        if "execution_allowed" in p and p["execution_allowed"] is not False:
            errors.append(ERR_INVALID_EXECUTION_ALLOWED)
        if "descriptive_only" in p and p["descriptive_only"] is not True:
            errors.append(ERR_INVALID_DESCRIPTIVE_ONLY)
        return _result(STATUS_INVALID if errors else STATUS_VALID, errors)
    except Exception:  # noqa: BLE001 - the validator never raises
        return _result(STATUS_UNAVAILABLE, [])
