"""
Capability Definition Candidate (Prompt 882, Section 16 - Capability Creation & Improvement)
============================================================================================
A deterministic, read-only CANDIDATE DEFINITION for the capability described by a
validated evolution proposal. It is NOT capability creation: it is a structured
description a later stage may inspect before any implementation is considered.
No source code, patch, project file, registry change, installation, loading,
replacement or execution is produced or authorized (`implementation_ready` and
`execution_allowed` are always False), and nothing touches the filesystem,
network, API, model, Memory, AEL or research. It never performs or allows
self-modification. Caller data is never normalized, altered or repaired.

  build_capability_definition_candidate(evolution_request, analysis_result,
                                        specification, plan, proposal,
                                        candidate_id=None)
  validate_capability_definition_candidate(candidate)

The public validators and builders of Prompts 876-881 are reused, not
re-implemented: request / analysis / specification validators,
validate_capability_evolution (+ _result), validate_capability_evolution_plan,
validate_capability_evolution_proposal, and build_capability_evolution_proposal
(to derive the one proposal the other four objects imply).

Build checks run in this fixed order; the first failure decides the status:
   1 request invalid                  invalid_request
   2 analysis invalid                 invalid_analysis
   3 specification invalid            invalid_specification
   4 Prompt 879 context (computed here) is an invalid result   invalid_validation
   5 plan invalid                     invalid_plan
   6 proposal invalid                 invalid_proposal
 7-16 every pairwise mismatch between request, analysis, specification, plan and
      proposal                        context_mismatch
      The proposal the Prompt 881 builder derives from the first four objects (and
      the supplied proposal's own proposal_id) must equal the supplied proposal;
      that single comparison covers every pair, because the Prompt 881 builder
      itself checks request/analysis/specification/plan consistency (steps 7-12, 14
      of this list) and the equality covers all proposal pairs (10, 13, 15, 16).
  17 candidate_id missing or invalid  invalid_candidate_id
  18 unsupported operation/status     unsupported_status
      supported: create + create_required + create_capability,
                 improve + improve_required + improve_capability
      (improve_or_conflict is never supported; an analysis with that status is
      stopped earlier, as invalid_plan or context_mismatch, and this step is the
      final guard)
  19 the built candidate fails its own validator   candidate_error
Any unexpected internal failure -> validation_error.

candidate_id is caller-supplied (text, <= 64 chars, the request-id rule) and is
never generated or defaulted.

Normalized candidate (exactly these fifteen keys):
  {"version", "candidate_id", "request_id", "operation", "capability_name",
   "purpose", "inputs", "outputs", "constraints", "existing_capability",
   "analysis_status", "plan_id", "proposal_id", "execution_allowed",
   "implementation_ready"}
  version "1"; request_id/operation/capability_name/inputs/outputs/constraints
  exactly as in the request and purpose exactly the request goal (lists copied,
  order kept); plan_id and proposal_id exactly those of the validated plan and
  proposal; create -> analysis_status "create_required", existing_capability None;
  improve -> analysis_status "improve_required", existing_capability a deep copy
  of the validated matching descriptor; execution_allowed and
  implementation_ready exactly False.

Build result (exactly these keys, fresh every call):
  {"status", "candidate", "execution_allowed", "executed"}
status "ready" only together with a valid candidate (else candidate is None);
both flags are always False.

validate_capability_definition_candidate(candidate) validates the exact 15-key
shape and every invariant above, reusing the Prompt 881 proposal validator on a
proposal-shaped view of the candidate. Result:
  {"valid", "errors", "execution_allowed", "executed"}
errors [{"code", "where"}], at most MAX_ERRORS; purely structural, read-only,
never raises. Bounded work, deterministic.
"""

import copy

from .capability_evolution_analysis import validate_capability_evolution_analysis
from .capability_evolution_plan import validate_capability_evolution_plan
from .capability_evolution_proposal import (PROPOSAL_TYPE, STATUS_UNSUPPORTED,
                                            build_capability_evolution_proposal,
                                            validate_capability_evolution_proposal)
from .capability_evolution_request import (REQUEST_VERSION,
                                           validate_capability_evolution_request)
from .capability_evolution_specification import validate_capability_evolution_specification
from .capability_evolution_validation import (STATUS_READY, validate_capability_evolution,
                                              validate_capability_evolution_result)
from .capability_registry import MAX_ERRORS

CANDIDATE_VERSION = REQUEST_VERSION

STATUS_INVALID_REQUEST = "invalid_request"
STATUS_INVALID_ANALYSIS = "invalid_analysis"
STATUS_INVALID_SPECIFICATION = "invalid_specification"
STATUS_INVALID_VALIDATION = "invalid_validation"
STATUS_INVALID_PLAN = "invalid_plan"
STATUS_INVALID_PROPOSAL = "invalid_proposal"
STATUS_CONTEXT = "context_mismatch"
STATUS_INVALID_CANDIDATE_ID = "invalid_candidate_id"
STATUS_UNSUPPORTED_STATUS = "unsupported_status"
STATUS_CANDIDATE_ERROR = "candidate_error"
STATUS_ERROR = "validation_error"

STATUSES = (STATUS_READY, STATUS_INVALID_REQUEST, STATUS_INVALID_ANALYSIS,
            STATUS_INVALID_SPECIFICATION, STATUS_INVALID_VALIDATION, STATUS_INVALID_PLAN,
            STATUS_INVALID_PROPOSAL, STATUS_CONTEXT, STATUS_INVALID_CANDIDATE_ID,
            STATUS_UNSUPPORTED_STATUS, STATUS_CANDIDATE_ERROR, STATUS_ERROR)

FIELDS = ("version", "candidate_id", "request_id", "operation", "capability_name", "purpose",
          "inputs", "outputs", "constraints", "existing_capability", "analysis_status",
          "plan_id", "proposal_id", "execution_allowed", "implementation_ready")

# (operation, analysis status, proposal type) combinations a candidate supports
SUPPORTED = (("create", "create_required", "create_capability"),
             ("improve", "improve_required", "improve_capability"))

ERR_NOT_DICT = "candidate_not_dict"
ERR_MISSING_KEY = "missing_key"
ERR_UNEXPECTED_KEY = "unexpected_key"
ERR_INVALID_CANDIDATE_ID = "invalid_candidate_id"
ERR_INVALID_PROPOSAL_ID = "invalid_proposal_id"
ERR_INVALID_PURPOSE = "invalid_purpose"
ERR_INVALID_IMPLEMENTATION_READY = "invalid_implementation_ready"
ERR_INCONSISTENT = "inconsistent_candidate"
ERR_INTERNAL = "validation_error"


# ------------------------------------------------------------------ build

def _build_result(status, candidate=None):
    return {"status": status, "candidate": candidate, "execution_allowed": False,
            "executed": False}


def build_capability_definition_candidate(evolution_request=None, analysis_result=None,
                                          specification=None, plan=None, proposal=None,
                                          candidate_id=None):
    """Build a fresh normalized candidate, or report the first failing check."""
    try:
        request, analysis, spec = evolution_request, analysis_result, specification
        if not validate_capability_evolution_request(request)["valid"]:
            return _build_result(STATUS_INVALID_REQUEST)
        if not validate_capability_evolution_analysis(analysis)["valid"]:
            return _build_result(STATUS_INVALID_ANALYSIS)
        if not validate_capability_evolution_specification(spec)["valid"]:
            return _build_result(STATUS_INVALID_SPECIFICATION)
        context = validate_capability_evolution(request, analysis, spec)
        if not validate_capability_evolution_result(context)["valid"]:
            return _build_result(STATUS_INVALID_VALIDATION)
        if not validate_capability_evolution_plan(plan)["valid"]:
            return _build_result(STATUS_INVALID_PLAN)
        if not validate_capability_evolution_proposal(proposal)["valid"]:
            return _build_result(STATUS_INVALID_PROPOSAL)

        if context["status"] == STATUS_READY and (
                context["request_id"] != request["request_id"]
                or context["capability_name"] != request["capability_name"]
                or context["operation"] != request["operation"]
                or context["analysis_status"] != analysis["status"]):
            return _build_result(STATUS_CONTEXT)

        derived = build_capability_evolution_proposal(request, analysis, spec, plan,
                                                      proposal["proposal_id"])
        unsupported = derived["status"] == STATUS_UNSUPPORTED
        if derived["status"] == STATUS_CONTEXT:
            return _build_result(STATUS_CONTEXT)
        if derived["status"] == STATUS_READY:
            if derived["proposal"] != proposal:
                return _build_result(STATUS_CONTEXT)
        elif not unsupported:
            return _build_result(STATUS_ERROR)

        if candidate_id is None or not _id_valid(candidate_id):
            return _build_result(STATUS_INVALID_CANDIDATE_ID)
        if (unsupported or context["status"] != STATUS_READY or context["ready"] is not True
                or (request["operation"], analysis["status"], proposal["proposal_type"])
                not in SUPPORTED):
            return _build_result(STATUS_UNSUPPORTED_STATUS)

        candidate = {
            "version": CANDIDATE_VERSION,
            "candidate_id": candidate_id,
            "request_id": request["request_id"],
            "operation": request["operation"],
            "capability_name": request["capability_name"],
            "purpose": request["goal"],
            "inputs": list(request["inputs"]),
            "outputs": list(request["outputs"]),
            "constraints": list(request["constraints"]),
            "existing_capability": copy.deepcopy(analysis["existing"]),
            "analysis_status": analysis["status"],
            "plan_id": plan["plan_id"],
            "proposal_id": proposal["proposal_id"],
            "execution_allowed": False,
            "implementation_ready": False,
        }
        if _candidate_errors(candidate):
            return _build_result(STATUS_CANDIDATE_ERROR)
        return _build_result(STATUS_READY, candidate)
    except Exception:
        return _build_result(STATUS_ERROR)


# ------------------------------------------------------------- validation

def _proposal_view(candidate, proposal_id):
    operation = candidate["operation"]
    kind = PROPOSAL_TYPE.get(operation, "create_capability") if type(operation) is str \
        else "create_capability"
    return {"version": candidate["version"], "proposal_id": proposal_id,
            "request_id": candidate["request_id"], "operation": operation,
            "capability_name": candidate["capability_name"], "goal": candidate["purpose"],
            "inputs": candidate["inputs"], "outputs": candidate["outputs"],
            "constraints": candidate["constraints"],
            "existing_capability": candidate["existing_capability"],
            "analysis_status": candidate["analysis_status"], "plan_id": candidate["plan_id"],
            "execution_allowed": candidate["execution_allowed"], "proposal_type": kind}


def _id_valid(value):
    """Reuse the Prompt 881 proposal validator for the text rule of an id."""
    view = {"version": "1", "proposal_id": value, "request_id": "r", "operation": "create",
            "capability_name": "c", "goal": "g", "inputs": [], "outputs": ["o"],
            "constraints": [], "existing_capability": None,
            "analysis_status": "create_required", "plan_id": "p", "execution_allowed": False,
            "proposal_type": "create_capability"}
    return validate_capability_evolution_proposal(view)["valid"]


_REMAP = {"invalid_proposal_id": (ERR_INVALID_CANDIDATE_ID, "candidate_id"),
          "inconsistent_proposal": (ERR_INCONSISTENT, None),
          "invalid_goal": (ERR_INVALID_PURPOSE, "purpose")}


def _candidate_errors(candidate):
    errors = []

    def add(code, where):
        if len(errors) < MAX_ERRORS and {"code": code, "where": where} not in errors:
            errors.append({"code": code, "where": where})

    if type(candidate) is not dict:
        add(ERR_NOT_DICT, "candidate")
        return errors
    for key in FIELDS:
        if key not in candidate:
            add(ERR_MISSING_KEY, key)
    for key in candidate:
        if type(key) is not str or key not in FIELDS:
            add(ERR_UNEXPECTED_KEY,
                key if type(key) is str and 0 < len(key) <= 40 else "<key>")
    if errors:
        return errors

    # Pass 1: everything shared with a proposal (candidate_id takes the proposal_id slot).
    for error in validate_capability_evolution_proposal(
            _proposal_view(candidate, candidate["candidate_id"]))["errors"]:
        code, where = _REMAP.get(error["code"], (error["code"], None))
        add(code, where or error["where"])
    # Pass 2: the text rule for the candidate's own proposal_id.
    for error in validate_capability_evolution_proposal(
            _proposal_view(candidate, candidate["proposal_id"]))["errors"]:
        if error["code"] == "invalid_proposal_id":
            add(ERR_INVALID_PROPOSAL_ID, "proposal_id")

    if candidate["implementation_ready"] is not False:
        add(ERR_INVALID_IMPLEMENTATION_READY, "implementation_ready")
    return errors


def validate_capability_definition_candidate(candidate=None):
    """Validation result for a normalized capability definition candidate."""
    try:
        errors = _candidate_errors(candidate)
    except Exception:
        errors = [{"code": ERR_INTERNAL, "where": "candidate"}]
    return {"valid": not errors, "errors": errors,
            "execution_allowed": False, "executed": False}
