"""
Runtime growth - Application Boundary (Prompt 945)
===================================================
`evaluate_runtime_growth_application_boundary(proposal, validation)` is a pure,
deterministic OBSERVATION of whether a validated, descriptive growth proposal
satisfies the structural boundary required before a future controlled application
stage. It returns a fresh dict with exactly: version, available, status, eligible,
request_id, proposal_type, execution_allowed, descriptive_only.

Eligible (available True, status "eligible", eligible True, request_id and
proposal_type copied from the proposal) only when the proposal is a dict,
`validation` exactly equals a fresh Prompt 944 validation of it, that validation
is valid, execution_allowed is False, descriptive_only is True and proposal_type
is one of the three supported types. Anything else - invalid, forged, unavailable
or mismatched - yields the unavailable result (available False, status
"unavailable", eligible False, request_id / proposal_type None), exposing none of
the untrusted proposal data.

Eligibility is NOT approval and NOT permission to execute: execution_allowed is
always False and descriptive_only always True. Nothing is applied, generated,
written, approved or invoked; no file, memory.db, network, subprocess, clock,
randomness or exec/eval access; inputs are never mutated; nothing raises. It does
not touch authorization or autonomy systems and is not wired into Core,
RuntimeCore, AEL, Android, capabilities, upgrades or Section 18.
"""

from runtime_growth import runtime_growth_proposal_validation as _validation

BOUNDARY_VERSION = "1"
STATUS_ELIGIBLE = "eligible"
STATUS_UNAVAILABLE = "unavailable"

FIELDS = ("version", "available", "status", "eligible", "request_id", "proposal_type",
          "execution_allowed", "descriptive_only")


def _unavailable_boundary():
    return {"version": BOUNDARY_VERSION, "available": False, "status": STATUS_UNAVAILABLE,
            "eligible": False, "request_id": None, "proposal_type": None,
            "execution_allowed": False, "descriptive_only": True}


def evaluate_runtime_growth_application_boundary(proposal, validation):
    """See the module docstring. Always returns a fresh dict; never raises."""
    try:
        if not isinstance(proposal, dict) or not isinstance(validation, dict):
            return _unavailable_boundary()
        expected = _validation.validate_runtime_growth_proposal(proposal)
        if expected.get("valid") is not True or validation != expected:
            return _unavailable_boundary()
        if proposal["execution_allowed"] is not False \
                or proposal["descriptive_only"] is not True:
            return _unavailable_boundary()
        proposal_type = proposal["proposal_type"]
        if proposal_type not in _validation.PROPOSAL_TYPE_SCOPES:
            return _unavailable_boundary()
        return {"version": BOUNDARY_VERSION, "available": True, "status": STATUS_ELIGIBLE,
                "eligible": True, "request_id": proposal["request_id"],
                "proposal_type": proposal_type, "execution_allowed": False,
                "descriptive_only": True}
    except Exception:  # noqa: BLE001 - the boundary never raises
        return _unavailable_boundary()
