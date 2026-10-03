"""
Final Self-Upgrade Acceptance Test (Prompt 386).

This is the acceptance test of the EXISTING Self-Upgrade lifecycle. It
adds no production code and no Self-Upgrade architecture: it re-uses the
Prompt 384 `DryRunHarness` (a linear sequence of calls to the existing
stage functions, each folded into the existing coordinator and persisted
with the existing context store) and adds only what an acceptance test
needs on top of a dry run - it ACTIVELY TRIES to break each safety rule
the prompt lists, and it folds everything it finds into one structured
final result:

    run_final_acceptance() -> {
        "acceptance_result":                 SELF_UPGRADE_ACCEPTED | SELF_UPGRADE_REQUIRES_FIX,
        "lifecycle_stages_tested":           [...19 stage names...],
        "stages_passed":                     [...],
        "stages_failed":                     [...],
        "detected_issues":                   ["[stage] what went wrong", ...],
        "human_approval_gates_worked":       bool,
        "persistence_resume_worked":         bool,
        "health_check_passed":               bool,
        "final_capability_lifecycle_state":  "VERIFIED" | ... | None,
        "checks_run":                        int,
    }

Five controlled scenarios feed that result (each in its own temporary
directory and SQLite file; nothing touches the project source, the
default database, the network, or any production registry):

  A. REFERENCE - the complete successful lifecycle, uninterrupted. After
     every stage: the coordinator's next action, the CapabilityLifecycle
     State (also re-derived independently), the persisted context (valid,
     references intact, never losing a reference once set), a read-only
     resume, and "never active / never executed / no unexpected process".
     At the two human gates it tries to slip past them (registration
     while pending, a forged APPROVED request dict, the first approval
     used as the registration approval, ...). At the end: idempotent
     re-registration, skipped/failed verification is never VERIFIED,
     no stage runs twice, no recursive loop, health check on the live
     services.
  B. RESTART - the same lifecycle with the process "restarted" at both
     approval gates, after registration, and after completion; resume
     must continue from the right stage, never repeat a completed one,
     never infer an approval, and never repair an inconsistent context.
  C. CORRECTION - a genuinely failing test goes through NEEDS_CORRECTION
     -> CORRECT -> one applied correction -> retest VERIFIED, and then
     through both gates to VERIFIED; CORRECT never repairs or retries by
     itself.
  D. REJECTION - a rejected first approval and a rejected registration
     approval each stop the lifecycle; nothing is registered.
  E. Fault injection (unit tests below, not part of the result):
     deliberate faults - an approval read as APPROVED when it is not, a
     registration that goes through without its approval, a registration
     that comes back enabled, a resume that restarts a completed stage,
     a failing health check - must each turn the result into
     SELF_UPGRADE_REQUIRES_FIX naming the right stage, proving the
     acceptance test fails clearly instead of silently passing.

The correction scenario (C) is the only one whose focused test imports
the generated module. A runtime error is the only kind of defect the
existing correction analysis will act on, so that test has to run the
generated function - and it does so only inside the existing sandboxed
test runner (Prompt 365), in a temporary workspace, at the explicit
"controlled testing" / "retest" steps. The registered capability's
handler is never called in any scenario.

Run directly:
    python -m unittest tests.test_self_upgrade_final_acceptance -v
    python -m tests.test_self_upgrade_final_acceptance      (prints the result as JSON)
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

PYTHON_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(PYTHON_ROOT)

from capabilities.capability_system import CapabilitySystem
from diagnostics.self_upgrade_health_check import (
    SelfUpgradeHealthCheck,
    STATUS_HEALTHY,
)
from memory.memory_system import MemorySystem
from planning.adaptive_plan_analyzer import AdaptivePlanAnalyzer
from self_upgrade import capability_builder as capability_builder_module
from self_upgrade import capability_file_apply as capability_file_apply_module
from self_upgrade import capability_test_execution as capability_test_execution_module
from self_upgrade.capability_build_spec import build_capability_build_spec
from self_upgrade.capability_correction_analysis import (
    build_capability_correction_analysis,
    STATUS_READY_FOR_CORRECTION,
)
from self_upgrade.capability_correction_apply import apply_capability_correction
from self_upgrade.capability_correction_verification import (
    verify_capability_correction,
    STATUS_VERIFIED as CORRECTION_VERIFIED,
)
from self_upgrade.capability_creation_plan import build_capability_creation_plan
from self_upgrade.capability_evaluation import (
    evaluate_capability_test_result,
    EVAL_NEEDS_CORRECTION,
)
from self_upgrade.capability_file_apply import apply_capability
from self_upgrade.capability_human_approval import request_capability_human_approval
from self_upgrade.capability_implementation_spec import build_capability_implementation_spec
from self_upgrade.capability_lifecycle import (
    build_capability_lifecycle_state,
    ALL_LIFECYCLE_STATUSES,
    LIFECYCLE_BUILT,
    LIFECYCLE_VALIDATED,
    LIFECYCLE_TESTED,
    LIFECYCLE_VERSIONED,
    LIFECYCLE_PENDING_APPROVAL,
    LIFECYCLE_APPROVED,
    LIFECYCLE_READY_FOR_REGISTRATION,
    LIFECYCLE_REGISTERED,
    LIFECYCLE_VERIFIED,
    LIFECYCLE_FAILED,
    LIFECYCLE_REJECTED,
)
from self_upgrade.capability_registration_executor import (
    register_approved_capability,
    REGISTRATION_RESULT_REGISTERED,
    REGISTRATION_RESULT_ALREADY_REGISTERED,
)
from self_upgrade.capability_registration_preparation import (
    prepare_capability_registration,
    REGISTRATION_STATUS_READY_FOR_REGISTRATION,
)
from self_upgrade.capability_registration_verifier import (
    verify_registered_capability,
    VERIFICATION_STATUS_VERIFIED,
)
from self_upgrade.capability_test_execution import run_capability_tests
from self_upgrade.self_upgrade_execution_context import (
    CONTEXT_FIELDS,
    validate_execution_context,
)
from self_upgrade.self_upgrade_lifecycle_coordinator import (
    DECISION_ANALYZE,
    DECISION_BUILD,
    DECISION_VALIDATE,
    DECISION_TEST,
    DECISION_CORRECT,
    DECISION_VERSION,
    DECISION_WAIT_FOR_APPROVAL,
    DECISION_PREPARE_REGISTRATION,
    DECISION_WAIT_FOR_REGISTRATION_APPROVAL,
    DECISION_REGISTER,
    DECISION_VERIFY_REGISTRATION,
    DECISION_COMPLETED,
    DECISION_BLOCKED,
)
from self_upgrade.self_upgrade_request import SelfUpgradeRequest
from self_upgrade.self_upgrade_resume_manager import (
    RESUME_STATUS_RESUMED,
    RESUME_STATUS_INVALID_CONTEXT,
)
from tests.test_self_upgrade_end_to_end_dry_run import (
    DryRunHarness,
    STAGES,
    EXPECTED_DECISIONS,
    CAPABILITY_NAME,
    TARGET_MODULE,
    TEST_TARGET,
    UPGRADE_REQUEST_ID,
)

ACCEPTED = "SELF_UPGRADE_ACCEPTED"
REQUIRES_FIX = "SELF_UPGRADE_REQUIRES_FIX"

# The lifecycle, in the order the prompt lists it.
S_REQUEST = "SelfUpgradeRequest"
S_ANALYSIS = "requirement_analysis"
S_PLANNING = "capability_planning"
S_BUILD_SPEC = "CapabilityBuildSpec"
S_BUILDING = "capability_building"
S_VALIDATION = "validation"
S_TESTING = "controlled_testing"
S_CORRECTION = "correction_path"
S_SNAPSHOT = "version_snapshot"
S_APPROVAL_1 = "first_human_approval"
S_REG_PREP = "registration_preparation"
S_APPROVAL_2 = "registration_approval"
S_REGISTRATION = "capability_registration"
S_VERIFICATION = "registration_verification"
S_LIFECYCLE_STATE = "CapabilityLifecycleState"
S_PERSISTENCE = "execution_context_persistence"
S_RESUME = "controlled_resume"
S_FINAL = "final_lifecycle_result"
S_HEALTH = "health_check"

ACCEPTANCE_STAGES = (
    S_REQUEST, S_ANALYSIS, S_PLANNING, S_BUILD_SPEC, S_BUILDING, S_VALIDATION, S_TESTING,
    S_CORRECTION, S_SNAPSHOT, S_APPROVAL_1, S_REG_PREP, S_APPROVAL_2, S_REGISTRATION,
    S_VERIFICATION, S_LIFECYCLE_STATE, S_PERSISTENCE, S_RESUME, S_FINAL, S_HEALTH,
)

# Which acceptance stage each harness stage belongs to.
PRIMARY_STAGE = {
    "submit_request": S_REQUEST, "analyze_and_specify": S_ANALYSIS, "build": S_BUILDING,
    "validate": S_VALIDATION, "apply_and_test": S_TESTING, "take_snapshot": S_SNAPSHOT,
    "submit_for_approval": S_APPROVAL_1, "approve_first": S_APPROVAL_1,
    "prepare_registration": S_REG_PREP, "approve_registration": S_APPROVAL_2,
    "register": S_REGISTRATION, "verify": S_VERIFICATION,
}
# The lifecycle status each stage must leave the capability in (None: the
# tracker has no build result yet, so there is nothing to compare).
EXPECTED_LIFECYCLE = {
    "submit_request": None, "analyze_and_specify": None, "build": LIFECYCLE_BUILT,
    "validate": LIFECYCLE_VALIDATED, "apply_and_test": LIFECYCLE_TESTED,
    "take_snapshot": LIFECYCLE_VERSIONED, "submit_for_approval": LIFECYCLE_PENDING_APPROVAL,
    "approve_first": LIFECYCLE_APPROVED, "prepare_registration": LIFECYCLE_APPROVED,
    "approve_registration": LIFECYCLE_READY_FOR_REGISTRATION,
    "register": LIFECYCLE_REGISTERED, "verify": LIFECYCLE_VERIFIED,
}
# Context reference fields that, once set, must never be lost.
REFERENCE_FIELDS = (
    "build_spec_reference", "implementation_spec_reference", "version_reference",
    "approval_request_id", "registration_plan_reference", "registration_result_reference",
    "verification_result_reference",
)
# The capability whose generated function has a runtime defect (scenario C).
DEFECTIVE_TEST_SOURCE = '''\
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from selfupgrade_dryrun_echo_module import selfupgrade_dryrun_echo


class GeneratedFunctionTests(unittest.TestCase):
    def test_returns_the_declared_output_shape(self):
        self.assertEqual(selfupgrade_dryrun_echo("hi"), {"echo": None})
'''


# ----------------------------------------------------------------------
# Collecting findings
# ----------------------------------------------------------------------
class _Findings:
    """Counts checks per acceptance stage and records every failed one.
    A stage that never recorded a check was never reached, and counts as
    failed - a crashed or short-circuited run can't pass by omission."""

    def __init__(self):
        self.checked = {stage: 0 for stage in ACCEPTANCE_STAGES}
        self.issues = []
        self.final_state = None

    def check(self, stage, condition, message):
        self.checked[stage] += 1
        if not condition:
            self.issues.append((stage, message))
        return bool(condition)

    def crashed(self, stage, exc):
        self.checked[stage] += 1
        self.issues.append((stage, f"scenario raised {type(exc).__name__}: {exc}"))

    def result(self):
        failed_stages = {stage for stage, _ in self.issues}
        stages_failed = [s for s in ACCEPTANCE_STAGES
                         if s in failed_stages or self.checked[s] == 0]
        stages_passed = [s for s in ACCEPTANCE_STAGES if s not in stages_failed]
        unreached = [s for s in ACCEPTANCE_STAGES if self.checked[s] == 0]
        issues = [f"[{stage}] {message}" for stage, message in self.issues]
        issues += [f"[{stage}] stage was never reached or checked" for stage in unreached]
        return {
            "acceptance_result": ACCEPTED if not stages_failed else REQUIRES_FIX,
            "lifecycle_stages_tested": list(ACCEPTANCE_STAGES),
            "stages_passed": stages_passed,
            "stages_failed": stages_failed,
            "detected_issues": issues,
            "human_approval_gates_worked":
                not ({S_APPROVAL_1, S_APPROVAL_2} & set(stages_failed)),
            "persistence_resume_worked":
                not ({S_PERSISTENCE, S_RESUME} & set(stages_failed)),
            "health_check_passed": S_HEALTH not in stages_failed,
            "final_capability_lifecycle_state": self.final_state,
            "checks_run": sum(self.checked.values()),
        }


def _sha(path):
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def _state_snapshot(harness):
    """Everything durable a read-only operation must leave alone: the
    whole key-value state table (approvals, contexts), the version
    history and the capability registry."""
    return (
        [(r["key"], r["value"]) for r in
         harness.memory.query("SELECT key, value FROM state ORDER BY key")],
        [(v["id"], v["version_label"], v["is_active"]) for v in harness.versions.history()],
        [(r["name"], r["enabled"], r["status"]) for r in harness.registry_rows()],
    )


def _decide(harness, **overrides):
    kwargs = dict(harness.evidence)
    kwargs.update(overrides)
    return harness.coordinator.decide(
        capability_name=CAPABILITY_NAME, approval_manager=harness.manager, **kwargs)


def _capability_snapshots(harness):
    """The version snapshots this upgrade took. The version history is
    seeded with a baseline `0.1.0-foundation` row, which stays as the
    rollback target; only the capability snapshot is this upgrade's."""
    return [v for v in harness.versions.history()
            if v["version_label"] == f"capability:{CAPABILITY_NAME}"]


def _snapshot_is_the_only_active_version(harness):
    history = harness.versions.history()
    active = [v for v in history if v["is_active"]]
    return (len(_capability_snapshots(harness)) == 1 and len(active) == 1
            and active[0]["version_label"] == f"capability:{CAPABILITY_NAME}"
            and any(v["version_label"] == "0.1.0-foundation" and not v["is_active"]
                    for v in history))


def _not_registered(result):
    return result["status"] != REGISTRATION_RESULT_REGISTERED


def _no_registry_rows(harness):
    return harness.registry_rows() == []


def _safety_after_stage(f, stage, h, popen):
    """The rules that must hold after EVERY stage of every scenario."""
    rows = h.registry_rows()
    f.check(stage, all(not r["enabled"] and r["status"] != "active" for r in rows),
            f"a registered capability is enabled/active after {stage}: {rows}")
    f.check(stage, h.probe.calls == [],
            f"the capability handler was executed after {stage}: {h.probe.calls}")
    f.check(stage, TARGET_MODULE not in sys.modules
            and "selfupgrade_dryrun_echo_module" not in sys.modules,
            f"the generated module was imported into this process after {stage}")
    f.check(stage, h.count_state_keys("self_upgrade_execution_context:%") == 1,
            "more than one execution context exists for the one upgrade request")
    return popen.call_count


# ----------------------------------------------------------------------
# A. Reference scenario
# ----------------------------------------------------------------------
def _scenario_reference(f):
    h = DryRunHarness()
    try:
        with mock.patch.object(subprocess, "Popen", wraps=subprocess.Popen) as popen:
            _run_reference(f, h, popen)
    finally:
        h.close()


def _run_reference(f, h, popen):
    seen_references = {}
    generated_hash = None
    current_stage = S_REQUEST
    try:
        for harness_stage in STAGES:
            current_stage = PRIMARY_STAGE[harness_stage]
            spawns_before = popen.call_count
            decision = getattr(h, harness_stage)()
            stage = current_stage

            # -- the coordinator reports the next valid action ------------------
            f.check(stage, decision["decision"] == EXPECTED_DECISIONS[harness_stage],
                    f"after {harness_stage} the next action is {decision['decision']}, "
                    f"expected {EXPECTED_DECISIONS[harness_stage]}")
            # -- no process is started except by the controlled test step -------
            spawned = popen.call_count - spawns_before
            f.check(stage, (spawned == 1) if harness_stage == "apply_and_test" else (spawned == 0),
                    f"{harness_stage} started {spawned} process(es); only the controlled "
                    "test step may start one")
            _safety_after_stage(f, stage, h, popen)

            # -- CapabilityLifecycleState ----------------------------------------
            expected_status = EXPECTED_LIFECYCLE[harness_stage]
            if expected_status is not None:
                independent = h.final_lifecycle_state()["current_status"]
                f.check(S_LIFECYCLE_STATE, decision["lifecycle_status"] == expected_status,
                        f"after {harness_stage} the coordinator reports lifecycle "
                        f"{decision['lifecycle_status']}, expected {expected_status}")
                f.check(S_LIFECYCLE_STATE, independent == expected_status,
                        f"after {harness_stage} an independently derived lifecycle state is "
                        f"{independent}, expected {expected_status}")

            # -- persisted context ------------------------------------------------
            context = h.store.load(UPGRADE_REQUEST_ID)
            errors = validate_execution_context(context) if context else ["no context"]
            f.check(S_PERSISTENCE, context is not None and not errors,
                    f"the persisted context is missing or inconsistent after {harness_stage}: {errors}")
            if context:
                f.check(S_PERSISTENCE, set(CONTEXT_FIELDS) <= set(context),
                        f"the persisted context lacks fields after {harness_stage}")
                f.check(S_PERSISTENCE, context["current_action"] == decision["decision"],
                        f"persisted current_action {context['current_action']} != "
                        f"decision {decision['decision']} after {harness_stage}")
                for field in REFERENCE_FIELDS:
                    if field in seen_references:
                        f.check(S_PERSISTENCE, context[field] == seen_references[field],
                                f"reference {field} was lost or changed after {harness_stage}")
                    if context[field] is not None:
                        seen_references[field] = copy.deepcopy(context[field])

            # -- controlled, read-only resume from what was just persisted ------
            before = _state_snapshot(h)
            resumed = [h.resume_manager.resume(UPGRADE_REQUEST_ID) for _ in range(3)]
            f.check(S_RESUME, all(r["resume_status"] == RESUME_STATUS_RESUMED for r in resumed),
                    f"resume after {harness_stage} was not RESUMED: "
                    f"{[r['resume_status'] for r in resumed]}")
            f.check(S_RESUME, all(r["decision"] and
                                  r["decision"]["decision"] == EXPECTED_DECISIONS[harness_stage]
                                  for r in resumed),
                    f"resume after {harness_stage} does not continue at "
                    f"{EXPECTED_DECISIONS[harness_stage]}: "
                    f"{[(r['decision'] or {}).get('decision') for r in resumed]}")
            f.check(S_RESUME, _state_snapshot(h) == before,
                    f"resuming after {harness_stage} changed durable state")

            # -- stage-specific checks ---------------------------------------------
            if harness_stage == "submit_request":
                _check_request_stage(f, h)
            elif harness_stage == "analyze_and_specify":
                _check_analysis_stages(f, h)
            elif harness_stage == "build":
                built = h.results["build_result"]
                f.check(S_BUILDING, built["capability_name"] == CAPABILITY_NAME
                        and f"def {CAPABILITY_NAME}(" in built["generated_source"],
                        "the build result does not contain the requested capability skeleton")
            elif harness_stage == "validate":
                f.check(S_VALIDATION, h.results["apply_request"]["capability_name"] == CAPABILITY_NAME,
                        "the validated apply request is for a different capability")
            elif harness_stage == "apply_and_test":
                generated_hash = _check_testing_stage(f, h)
            elif harness_stage == "take_snapshot":
                _check_snapshot_stage(f, h)
            elif harness_stage == "submit_for_approval":
                _check_first_gate_pending(f, h)
            elif harness_stage == "approve_first":
                _check_first_gate_approved(f, h)
            elif harness_stage == "prepare_registration":
                _check_second_gate_pending(f, h)
            elif harness_stage == "approve_registration":
                f.check(S_APPROVAL_2, _no_registry_rows(h),
                        "approving the registration registered something; approval must "
                        "record a decision only")
            elif harness_stage == "register":
                _check_registration_stage(f, h)
            elif harness_stage == "verify":
                _check_verification_stage(f, h)

        # ---- after the last stage ------------------------------------------------
        current_stage = S_FINAL
        _check_final_result(f, h, generated_hash)
        current_stage = S_HEALTH
        _check_health(f, h)
        current_stage = S_FINAL
        _check_no_recursion(f, h)
    except Exception as exc:  # any crash is a failed stage, never a silent pass
        f.crashed(current_stage, exc)


def _check_request_stage(f, h):
    request = h.results["request"]
    f.check(S_REQUEST, request.is_valid(), "the acceptance request is not a valid SelfUpgradeRequest")
    context = h.store.load(UPGRADE_REQUEST_ID)
    f.check(S_REQUEST, context is not None and context["capability_name"] == CAPABILITY_NAME,
            "the valid request did not create an execution context for its capability")
    # A malformed request may be recorded, but it must never reach BUILD.
    for label, kwargs in (
            ("blank goal", dict(goal="  ", requested_capability=CAPABILITY_NAME)),
            ("blank capability", dict(goal="do it", requested_capability="")),
            ("blank id", dict(request_id="", goal="do it", requested_capability=CAPABILITY_NAME))):
        kwargs.setdefault("request_id", "malformed-request")
        bad = SelfUpgradeRequest(reason="acceptance", **kwargs)
        plan = build_capability_creation_plan(h.analyzer.analyze_self_upgrade_request(bad))
        verdict = h.coordinator.decide(capability_name=CAPABILITY_NAME,
                                       self_upgrade_request=bad, creation_plan=plan)["decision"]
        f.check(S_REQUEST, not bad.is_valid() and plan["status"] != "READY"
                and verdict != DECISION_BUILD,
                f"a malformed request ({label}) got past analysis: plan={plan['status']}, "
                f"decision={verdict}")
    unknown = SelfUpgradeRequest(request_id="r", goal="g", requested_capability=CAPABILITY_NAME,
                                 status="NOT_A_STATUS")
    f.check(S_REQUEST, h.coordinator.decide(
        capability_name=CAPABILITY_NAME, self_upgrade_request=unknown)["decision"] != DECISION_ANALYZE,
        "a request with an unrecognized status was allowed to enter ANALYZE")


def _check_analysis_stages(f, h):
    r = h.results
    f.check(S_ANALYSIS, r["analysis"]["requested_capability"] == CAPABILITY_NAME
            and r["analysis"]["blockers"] == [],
            f"requirement analysis is blocked or names another capability: {r['analysis']}")
    f.check(S_PLANNING, r["creation_plan"]["status"] == "READY"
            and r["creation_plan"]["capability_name"] == CAPABILITY_NAME
            and r["implementation_spec"]["status"] == "READY"
            and r["implementation_spec"]["interface_name"] == CAPABILITY_NAME,
            "capability creation / implementation planning did not produce READY plans")
    spec = r["build_spec"]
    f.check(S_BUILD_SPEC, spec["status"] == "READY" and spec["capability_name"] == CAPABILITY_NAME
            and spec["target_module"] == TARGET_MODULE and spec["implementation_steps"]
            and spec["input_schema"] and spec["output_schema"],
            f"the CapabilityBuildSpec is incomplete: {sorted(spec)}")
    context = h.store.load(UPGRADE_REQUEST_ID)
    f.check(S_PERSISTENCE, context["build_spec_reference"] == spec
            and context["implementation_spec_reference"] == r["implementation_spec"],
            "the persisted context does not reference the build spec / implementation spec")


def _check_testing_stage(f, h):
    r = h.results
    f.check(S_TESTING, r["applied"]["status"] == "APPLIED"
            and os.path.dirname(r["applied"]["file_path"]) == h.workspace,
            "the capability file was not applied inside the temporary workspace")
    f.check(S_TESTING, r["test_result"]["status"] == "PASSED"
            and r["test_result"]["tests_run"] == 2 and r["test_result"]["tests_failed"] == 0,
            f"controlled testing did not pass cleanly: {r['test_result']['status']}")
    f.check(S_TESTING, r["evaluation"]["evaluation_status"] == "SUCCESS"
            and r["evaluation"]["correction_required"] is False,
            "the test evaluation is not SUCCESS")
    return _sha(r["applied"]["file_path"])


def _check_snapshot_stage(f, h):
    request = h.results["human_request"]
    f.check(S_SNAPSHOT, request["status"] == "PENDING_APPROVAL"
            and request["verification_status"] == "VERIFIED" and request["rollback_available"],
            "the snapshot request is not a verified, rollback-able PENDING_APPROVAL request")
    f.check(S_SNAPSHOT, _snapshot_is_the_only_active_version(h) and request["version"] is not None,
            "expected exactly one capability snapshot, active, with the baseline kept for rollback; "
            f"found {[(v['version_label'], v['is_active']) for v in h.versions.history()]}")
    reference = h.store.load(UPGRADE_REQUEST_ID)["version_reference"]
    f.check(S_SNAPSHOT, isinstance(reference, dict)
            and reference.get("id") == request["version"]["id"]
            and reference.get("version_label") == request["version"]["version_label"],
            f"the persisted context lost the version/snapshot reference: {reference}")


def _check_first_gate_pending(f, h):
    request = h.results["human_request"]
    request_id = request["request_id"]
    f.check(S_APPROVAL_1, h.manager.get_status(request_id)["status"] == "PENDING_APPROVAL",
            "the first approval request is not PENDING_APPROVAL")
    first = _decide(h)
    f.check(S_APPROVAL_1, all(_decide(h)["decision"] == DECISION_WAIT_FOR_APPROVAL for _ in range(3))
            and first["decision"] == DECISION_WAIT_FOR_APPROVAL,
            "waiting for the first approval did not stay WAIT_FOR_APPROVAL (approval inferred?)")
    # A request dict that merely CLAIMS to be approved must never move the
    # lifecycle forward (the existing lifecycle refuses it outright).
    forged = _decide(h, human_approval_request=dict(request, status="APPROVED"))
    f.check(S_APPROVAL_1, forged["decision"] in (DECISION_WAIT_FOR_APPROVAL, "INVALID")
            and forged["lifecycle_status"] not in (LIFECYCLE_APPROVED, LIFECYCLE_READY_FOR_REGISTRATION),
            "a caller-supplied request dict claiming APPROVED moved the lifecycle past the "
            f"first gate: {forged['decision']}/{forged['lifecycle_status']}")
    prep = prepare_capability_registration(request, h.manager, h.results["build_spec"])
    f.check(S_APPROVAL_1, prep["status"] != REGISTRATION_STATUS_READY_FOR_REGISTRATION,
            "registration preparation succeeded while the first approval is still pending")
    result = register_approved_capability(request_id, h.manager, h.capability_system)
    f.check(S_APPROVAL_1, _not_registered(result) and _no_registry_rows(h),
            f"registration went through with only a pending first approval: {result['status']}")


def _check_first_gate_approved(f, h):
    request_id = h.results["human_request"]["request_id"]
    f.check(S_APPROVAL_1, h.manager.get_status(request_id)["status"] == "APPROVED",
            "the explicit first approval was not recorded")
    f.check(S_APPROVAL_1, _no_registry_rows(h), "approving the first gate registered a capability")
    # The first approval is not the registration approval.
    result = register_approved_capability(request_id, h.manager, h.capability_system)
    f.check(S_APPROVAL_2, _not_registered(result) and _no_registry_rows(h),
            f"the first (snapshot) approval was accepted as a registration approval: {result['status']}")


def _check_second_gate_pending(f, h):
    registration_id = h.results["registration_request_id"]
    f.check(S_REG_PREP, h.results["preparation"]["status"] == REGISTRATION_STATUS_READY_FOR_REGISTRATION
            and h.results["registration_plan"]["status"] == "READY_FOR_APPROVED_REGISTRATION"
            and h.results["registration_request"]["status"] == "PENDING_APPROVAL",
            "registration preparation / plan / approval request are not in their expected states")
    f.check(S_REG_PREP, _no_registry_rows(h), "registration preparation registered a capability")
    f.check(S_APPROVAL_2, h.manager.get_status(registration_id)["status"] == "PENDING_APPROVAL",
            "the registration approval request is not PENDING_APPROVAL")
    f.check(S_APPROVAL_2, all(_decide(h)["decision"] == DECISION_WAIT_FOR_REGISTRATION_APPROVAL
                              for _ in range(3)),
            "waiting for the registration approval did not stay WAIT_FOR_REGISTRATION_APPROVAL")
    result = register_approved_capability(registration_id, h.manager, h.capability_system)
    f.check(S_APPROVAL_2, _not_registered(result) and _no_registry_rows(h),
            f"registration went through without the registration approval: {result['status']}")
    f.check(S_APPROVAL_2, _decide(h)["decision"] == DECISION_WAIT_FOR_REGISTRATION_APPROVAL,
            "an attempted registration without approval changed the lifecycle decision")


def _check_registration_stage(f, h):
    result = h.results["registration_result"]
    rows = h.registry_rows()
    f.check(S_REGISTRATION, result["status"] == REGISTRATION_RESULT_REGISTERED and len(rows) == 1,
            f"registration after explicit approval failed: {result['status']}, rows={len(rows)}")
    f.check(S_REGISTRATION, rows and rows[0]["name"] == CAPABILITY_NAME
            and not rows[0]["enabled"] and rows[0]["status"] == "registered",
            f"the registered capability is not 'registered'/disabled: {rows}")
    again = register_approved_capability(
        h.results["registration_request_id"], h.manager, h.capability_system)
    f.check(S_REGISTRATION, again["status"] == REGISTRATION_RESULT_ALREADY_REGISTERED
            and len(h.registry_rows()) == 1,
            f"registering twice was not idempotent: {again['status']}, rows={len(h.registry_rows())}")
    # Registered is not verified: verification can not be skipped.
    unverified = build_capability_lifecycle_state(
        CAPABILITY_NAME, build_result=h.results["build_result"],
        apply_request=h.results["apply_request"], test_evaluation=h.results["evaluation"],
        human_approval_request=h.results["human_request"], approval_manager=h.manager,
        registration_plan=h.results["registration_plan"],
        registration_request_id=h.results["registration_request_id"],
        registration_result=result)
    f.check(S_VERIFICATION, unverified["current_status"] == LIFECYCLE_REGISTERED,
            f"a registered capability with no verification reports {unverified['current_status']}")
    f.check(S_VERIFICATION, _decide(h)["decision"] == DECISION_VERIFY_REGISTRATION,
            "the lifecycle did not require verification after registration")


def _check_verification_stage(f, h):
    result = h.results["verification_result"]
    f.check(S_VERIFICATION, result["status"] == VERIFICATION_STATUS_VERIFIED and not result["mismatches"],
            f"registration verification did not verify: {result['status']}")
    # A verification against a registry that lacks the capability must not pass.
    other = MemorySystem(os.path.join(h.root, "state", "empty-registry.db"))
    try:
        empty = verify_registered_capability(
            h.results["registration_result"], h.manager, CapabilitySystem(other))
        f.check(S_VERIFICATION, empty["status"] != VERIFICATION_STATUS_VERIFIED,
                "verification passed against a registry that does not contain the capability")
    finally:
        other._conn.close()


def _check_final_result(f, h, generated_hash):
    report = h.final_report()
    f.final_state = report["final_lifecycle_state"]
    f.check(S_FINAL, report["final_lifecycle_state"] == LIFECYCLE_VERIFIED and not report["errors"],
            f"the final lifecycle state is {report['final_lifecycle_state']} "
            f"with errors {report['errors']}")
    f.check(S_FINAL, "ACTIVE" not in ALL_LIFECYCLE_STATUSES
            and all(not r["enabled"] for r in h.registry_rows()),
            "the lifecycle can express, or the registry holds, an active capability")
    f.check(S_FINAL, h.last_decision["decision"] == DECISION_COMPLETED,
            "the lifecycle did not end at COMPLETED")
    # Every reference is present, and they all agree with each other.
    context = report["execution_context"]
    request_id = h.results["human_request"]["request_id"]
    registration_id = h.results["registration_request_id"]
    f.check(S_PERSISTENCE, all(context[field] is not None for field in REFERENCE_FIELDS),
            f"the final context lost references: "
            f"{[x for x in REFERENCE_FIELDS if context[x] is None]}")
    f.check(S_PERSISTENCE,
            context["approval_request_id"] == request_id
            and context["registration_result_reference"]["request_id"] == registration_id
            and context["verification_result_reference"]["request_id"] == registration_id
            and context["registration_result_reference"]["approval_request_id"] == request_id
            and context["verification_result_reference"]["approval_request_id"] == request_id
            and context["current_lifecycle_state"]["registration_request_id"] == registration_id,
            "the approval / registration / verification references do not agree with each other")
    f.check(S_PERSISTENCE, context["last_error"] is None, f"last_error is set: {context['last_error']}")
    # Nothing ran twice and nothing changed the generated code.
    f.check(S_FINAL, h.count_state_keys("capability_approval:%") == 2
            and len(_capability_snapshots(h)) == 1 and len(h.registry_rows()) == 1,
            "an approval request, a snapshot or a registry row was created more than once")
    f.check(S_FINAL, h.decisions == [EXPECTED_DECISIONS[s] for s in STAGES],
            f"a stage ran out of order or twice: {h.decisions}")
    f.check(S_FINAL, _sha(h.results["applied"]["file_path"]) == generated_hash,
            "the generated capability file was modified after it was tested")
    f.check(S_FINAL, h.probe.calls == [], "the registered capability's handler was executed")


def _check_health(f, h):
    before = _state_snapshot(h)
    live = SelfUpgradeHealthCheck(
        version_system=h.versions, approval_manager=h.manager, capability_system=h.capability_system,
        context_store=h.store, coordinator=h.coordinator, resume_manager=h.resume_manager).check()
    f.check(S_HEALTH, live["status"] == STATUS_HEALTHY and live["failed_components"] == []
            and live["checks_passed"] == live["checks_run"] and live["live_checked"] is True,
            f"the live health check is not HEALTHY: {live['status']} {live['failed_components']}")
    static = SelfUpgradeHealthCheck().check()
    f.check(S_HEALTH, static["status"] == STATUS_HEALTHY and static["live_checked"] is False,
            f"the static health check is not HEALTHY: {static['status']}")
    f.check(S_HEALTH, _state_snapshot(h) == before, "the health check changed durable state")


def _check_no_recursion(f, h):
    """At the terminal state, asking again - many times, by every route -
    starts nothing: no analysis, build, apply, test, approval, snapshot,
    registration or new upgrade request."""
    before = _state_snapshot(h)
    with mock.patch.object(AdaptivePlanAnalyzer, "analyze_self_upgrade_request") as analyze, \
            mock.patch.object(capability_builder_module, "build_capability") as build, \
            mock.patch.object(capability_file_apply_module, "apply_capability") as apply_, \
            mock.patch.object(capability_test_execution_module, "run_capability_tests") as run, \
            mock.patch.object(subprocess, "Popen") as popen:
        for _ in range(25):
            f.check(S_FINAL, _decide(h)["decision"] == DECISION_COMPLETED,
                    "repeated decisions at COMPLETED changed")
            f.check(S_RESUME, h.resume_manager.resume(UPGRADE_REQUEST_ID)["decision"]["decision"]
                    == DECISION_COMPLETED, "repeated resume at COMPLETED changed")
            new_context, decision = h.coordinator.advance(
                h.store.load(UPGRADE_REQUEST_ID), capability_name=CAPABILITY_NAME,
                approval_manager=h.manager, **h.evidence)
            f.check(S_FINAL, decision["decision"] == DECISION_COMPLETED,
                    "advancing a completed lifecycle did not stay COMPLETED")
        started = (analyze.call_count, build.call_count, apply_.call_count,
                   run.call_count, popen.call_count)
    f.check(S_FINAL, started == (0, 0, 0, 0, 0),
            f"a completed lifecycle started another cycle (analyze/build/apply/test/process): {started}")
    f.check(S_FINAL, _state_snapshot(h) == before,
            "repeated decisions/resumes at COMPLETED changed durable state")


# ----------------------------------------------------------------------
# B. Restart scenario
# ----------------------------------------------------------------------
def _scenario_restart(f):
    h = DryRunHarness()
    stage = S_RESUME
    try:
        def resumed_at(expected, label):
            r = h.resume_manager.resume(UPGRADE_REQUEST_ID)
            f.check(S_RESUME, r["resume_status"] == RESUME_STATUS_RESUMED and r["decision"]
                    and r["decision"]["decision"] == expected,
                    f"after a restart {label} resume reported "
                    f"{r['resume_status']}/{(r['decision'] or {}).get('decision')}, expected {expected}")
            context = h.store.load(UPGRADE_REQUEST_ID)
            f.check(S_PERSISTENCE, not validate_execution_context(context),
                    f"the context reloaded after a restart {label} is inconsistent")
            return context

        h.run_through("submit_for_approval")
        h.restart()
        context = resumed_at(DECISION_WAIT_FOR_APPROVAL, "at the first gate")
        f.check(S_APPROVAL_1, h.decide()["decision"] == DECISION_WAIT_FOR_APPROVAL
                and context["approval_request_id"] is not None,
                "a restart at the first gate inferred an approval or lost the approval reference")
        h.approve_first()
        h.prepare_registration()

        h.restart()
        context = resumed_at(DECISION_WAIT_FOR_REGISTRATION_APPROVAL, "at the registration gate")
        f.check(S_APPROVAL_2, h.decide()["decision"] == DECISION_WAIT_FOR_REGISTRATION_APPROVAL
                and _no_registry_rows(h),
                "a restart at the registration gate inferred an approval or registered something")
        h.approve_registration()
        h.register()

        h.restart()
        context = resumed_at(DECISION_VERIFY_REGISTRATION, "after registration")
        f.check(S_RESUME, len(h.registry_rows()) == 1,
                "resuming after registration registered again or lost the registration")
        f.check(S_PERSISTENCE, context["registration_result_reference"]["status"]
                == REGISTRATION_RESULT_REGISTERED,
                "the registration result was not persisted before the restart")
        # The context keeps trimmed references (status and the ids that link
        # approval -> registration -> verification); the full records live in
        # ApprovalManager. Verification must not trust the trimmed copy ...
        trimmed = verify_registered_capability(
            context["registration_result_reference"], h.manager, h.capability_system)
        f.check(S_RESUME, trimmed["status"] != VERIFICATION_STATUS_VERIFIED,
                "verification accepted an incomplete (trimmed) registration result")
        # ... so the continuation rebuilds the full result the way the existing
        # design provides: an idempotent replay of the approved registration,
        # which must add nothing and must not register a second time.
        replay = register_approved_capability(
            context["current_lifecycle_state"]["registration_request_id"],
            h.manager, h.capability_system)
        f.check(S_RESUME, replay["status"] == REGISTRATION_RESULT_ALREADY_REGISTERED
                and len(h.registry_rows()) == 1 and h.probe.calls == [],
                f"replaying the approved registration after a restart was not idempotent: "
                f"{replay['status']}, rows={len(h.registry_rows())}")
        h.results["registration_result"] = replay
        h.evidence["registration_result"] = replay
        h.verify()

        h.restart()
        context = resumed_at(DECISION_COMPLETED, "after completion")
        state = h.final_report()
        f.check(S_FINAL, context["current_lifecycle_state"]["current_status"] == LIFECYCLE_VERIFIED
                and state["verification_result"]["status"] == VERIFICATION_STATUS_VERIFIED,
                "the lifecycle resumed across four restarts did not end VERIFIED")
        f.check(S_RESUME, h.count_state_keys("capability_approval:%") == 2
                and len(_capability_snapshots(h)) == 1 and len(h.registry_rows()) == 1
                and h.count_state_keys("self_upgrade_execution_context:%") == 1,
                "resuming repeated a completed stage (another approval, snapshot, registration or context)")
        f.check(S_FINAL, h.probe.calls == [] and all(not r["enabled"] for r in h.registry_rows()),
                "a resumed lifecycle executed or enabled the capability")

        # An inconsistent persisted context is reported, never repaired or resumed from.
        tampered = copy.deepcopy(h.store.load(UPGRADE_REQUEST_ID))
        tampered["capability_name"] = "some_other_capability"
        h.store.save(tampered)
        bad = h.resume_manager.resume(UPGRADE_REQUEST_ID)
        f.check(S_PERSISTENCE, bad["resume_status"] == RESUME_STATUS_INVALID_CONTEXT and bad["errors"]
                and h.store.load(UPGRADE_REQUEST_ID)["capability_name"] == "some_other_capability",
                f"an inconsistent persisted context was accepted or silently repaired: "
                f"{bad['resume_status']}")
        f.check(S_RESUME, bad["decision"] is None, "resume returned a decision for an invalid context")
    except Exception as exc:
        f.crashed(stage, exc)
    finally:
        h.close()


# ----------------------------------------------------------------------
# C. Correction scenario
# ----------------------------------------------------------------------
def _scenario_correction(f):
    h = DryRunHarness()
    try:
        with mock.patch.object(subprocess, "Popen", wraps=subprocess.Popen) as popen:
            _run_correction(f, h, popen)
    except Exception as exc:
        f.crashed(S_CORRECTION, exc)
    finally:
        h.close()


def _run_correction(f, h, popen):
    h.run_through("validate")
    applied = apply_capability(h.results["apply_request"], h.workspace, allowed_dirs=[h.workspace])
    path = applied["file_path"]
    with open(path, encoding="utf-8") as handle:
        source = handle.read()
    # A controlled build defect: valid Python, wrong at runtime.
    defective = source.replace("return {'echo': None}", "return {'echo': missing_name}")
    f.check(S_CORRECTION, defective != source, "could not inject the controlled defect")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(defective)
    with open(os.path.join(h.workspace, TEST_TARGET + ".py"), "w", encoding="utf-8") as handle:
        handle.write(DEFECTIVE_TEST_SOURCE)

    failed_test = run_capability_tests(applied, h.workspace, TEST_TARGET, allowed_dirs=[h.workspace])
    evaluation = evaluate_capability_test_result(failed_test)
    h.evidence["test_evaluation"] = evaluation
    decision = h.advance()
    f.check(S_CORRECTION, failed_test["status"] == "FAILED"
            and evaluation["evaluation_status"] == EVAL_NEEDS_CORRECTION
            and evaluation["correction_required"] is True,
            f"a failing test was not classified NEEDS_CORRECTION: {evaluation['evaluation_status']}")
    f.check(S_CORRECTION, decision["decision"] == DECISION_CORRECT
            and decision["lifecycle_status"] == LIFECYCLE_FAILED,
            f"a failed test did not lead to CORRECT: {decision['decision']}/{decision['lifecycle_status']}")

    # CORRECT is a decision only: asking again never repairs, retests or loops.
    hash_before, spawns_before, state_before = _sha(path), popen.call_count, _state_snapshot(h)
    with mock.patch.object(capability_test_execution_module, "run_capability_tests") as rerun:
        stable = all(_decide(h)["decision"] == DECISION_CORRECT for _ in range(25))
    f.check(S_CORRECTION, stable and rerun.call_count == 0 and popen.call_count == spawns_before
            and _sha(path) == hash_before and _state_snapshot(h) == state_before,
            "the CORRECT decision repaired, retested or changed something by itself")

    analysis = build_capability_correction_analysis(evaluation, allowed_dirs=[h.workspace])
    f.check(S_CORRECTION, analysis["status"] == STATUS_READY_FOR_CORRECTION,
            f"correction analysis is not READY_FOR_CORRECTION: {analysis['status']}")
    correction = apply_capability_correction(
        analysis, [{"old_text": "missing_name", "new_text": "None"}], allowed_dirs=[h.workspace])
    f.check(S_CORRECTION, correction["status"] == "APPLIED" and correction["correction_applied"] is True,
            f"the single controlled correction was not applied: {correction['status']} "
            f"{correction.get('error')}")
    verification = verify_capability_correction(
        failed_test, correction, h.workspace, TEST_TARGET, allowed_dirs=[h.workspace])
    f.check(S_CORRECTION, verification["status"] == CORRECTION_VERIFIED
            and verification["correction_verified"] and verification["improved"]
            and verification["previous_test_result"]["status"] == "FAILED"
            and verification["retest_evaluation"]["evaluation_status"] == "SUCCESS",
            f"the correction was not verified by the retest: {verification['status']} "
            f"{verification['errors']}")
    f.check(S_CORRECTION, popen.call_count == 2,
            f"expected exactly the test and the retest to start processes, saw {popen.call_count}")

    # The lifecycle continues from VERSION - completed stages are not restarted.
    h.results.update(applied=applied, test_result=failed_test,
                     evaluation=verification["retest_evaluation"], verification=verification)
    h.evidence["test_evaluation"] = verification["retest_evaluation"]
    decision = h.advance()
    f.check(S_CORRECTION, decision["decision"] == DECISION_VERSION
            and decision["lifecycle_status"] == LIFECYCLE_TESTED,
            f"after a verified correction the next action is {decision['decision']}, expected VERSION")
    human_request = request_capability_human_approval(
        verification, h.versions, allowed_dirs=[h.workspace])
    h.results["human_request"] = human_request
    h.evidence["human_approval_request"] = human_request
    decision = h.advance()
    f.check(S_CORRECTION, decision["decision"] == DECISION_WAIT_FOR_APPROVAL
            and human_request["status"] == "PENDING_APPROVAL" and _snapshot_is_the_only_active_version(h),
            "a corrected capability did not reach exactly one pending snapshot approval")
    for harness_stage in ("submit_for_approval", "approve_first", "prepare_registration",
                          "approve_registration", "register", "verify"):
        getattr(h, harness_stage)()
        _safety_after_stage(f, S_CORRECTION, h, popen)
    f.check(S_CORRECTION, h.decisions == [
        DECISION_ANALYZE, DECISION_BUILD, DECISION_VALIDATE, DECISION_TEST, DECISION_CORRECT,
        DECISION_VERSION,
        DECISION_WAIT_FOR_APPROVAL, DECISION_WAIT_FOR_APPROVAL, DECISION_PREPARE_REGISTRATION,
        DECISION_WAIT_FOR_REGISTRATION_APPROVAL, DECISION_REGISTER, DECISION_VERIFY_REGISTRATION,
        DECISION_COMPLETED],
        f"the corrected lifecycle took an unexpected path: {h.decisions}")
    f.check(S_CORRECTION, h.final_report()["final_lifecycle_state"] == LIFECYCLE_VERIFIED
            and h.count_state_keys("capability_approval:%") == 2 and len(h.registry_rows()) == 1,
            "the corrected lifecycle did not end VERIFIED through both approval gates")


# ----------------------------------------------------------------------
# D. Rejection scenarios
# ----------------------------------------------------------------------
def _scenario_rejections(f):
    h = DryRunHarness()
    try:
        h.run_through("submit_for_approval")
        request = h.results["human_request"]
        h.manager.reject(request["request_id"])
        decision = h.advance()
        f.check(S_APPROVAL_1, decision["decision"] == DECISION_BLOCKED
                and decision["lifecycle_status"] == LIFECYCLE_REJECTED,
                f"a rejected first approval did not stop the lifecycle: {decision['decision']}")
        prep = prepare_capability_registration(request, h.manager, h.results["build_spec"])
        f.check(S_APPROVAL_1, prep["status"] != REGISTRATION_STATUS_READY_FOR_REGISTRATION
                and _no_registry_rows(h),
                "registration was prepared or performed after a rejected first approval")
        h.manager.approve(request["request_id"])
        f.check(S_APPROVAL_1, h.manager.get_status(request["request_id"])["status"] == "REJECTED"
                and _decide(h)["decision"] == DECISION_BLOCKED,
                "a rejected approval was later flipped to approved")
    except Exception as exc:
        f.crashed(S_APPROVAL_1, exc)
    finally:
        h.close()

    h = DryRunHarness()
    try:
        h.run_through("prepare_registration")
        registration_id = h.results["registration_request_id"]
        h.manager.reject(registration_id)
        decision = h.advance()
        f.check(S_APPROVAL_2, decision["decision"] == DECISION_BLOCKED,
                f"a rejected registration approval did not stop the lifecycle: {decision['decision']}")
        result = register_approved_capability(registration_id, h.manager, h.capability_system)
        f.check(S_APPROVAL_2, _not_registered(result) and _no_registry_rows(h),
                f"a rejected registration approval still registered the capability: {result['status']}")
        h.manager.approve(registration_id)
        result = register_approved_capability(registration_id, h.manager, h.capability_system)
        f.check(S_APPROVAL_2, _not_registered(result) and _no_registry_rows(h),
                "a rejected registration approval was later flipped to approved")
    except Exception as exc:
        f.crashed(S_APPROVAL_2, exc)
    finally:
        h.close()


# ----------------------------------------------------------------------
# The final structured result
# ----------------------------------------------------------------------
def run_final_acceptance():
    """Run every scenario against the EXISTING implementation and return
    the structured final acceptance result (see the module docstring)."""
    findings = _Findings()
    for scenario in (_scenario_reference, _scenario_restart, _scenario_correction,
                     _scenario_rejections):
        try:
            scenario(findings)
        except Exception as exc:  # a scenario can never make the run raise
            findings.crashed(S_FINAL, exc)
    return findings.result()


class FinalAcceptanceTests(unittest.TestCase):
    """The acceptance verdict itself."""

    @classmethod
    def setUpClass(cls):
        cls.result = run_final_acceptance()

    def test_the_final_acceptance_result_is_accepted(self):
        self.assertEqual(self.result["detected_issues"], [])
        self.assertEqual(self.result["stages_failed"], [])
        self.assertEqual(self.result["acceptance_result"], ACCEPTED)

    def test_the_result_has_exactly_the_required_fields(self):
        self.assertEqual(set(self.result), {
            "acceptance_result", "lifecycle_stages_tested", "stages_passed", "stages_failed",
            "detected_issues", "human_approval_gates_worked", "persistence_resume_worked",
            "health_check_passed", "final_capability_lifecycle_state", "checks_run"})

    def test_every_lifecycle_stage_is_tested_and_passed(self):
        self.assertEqual(len(ACCEPTANCE_STAGES), 19)
        self.assertEqual(self.result["lifecycle_stages_tested"], list(ACCEPTANCE_STAGES))
        self.assertEqual(self.result["stages_passed"], list(ACCEPTANCE_STAGES))

    def test_both_human_approval_gates_worked(self):
        self.assertIs(self.result["human_approval_gates_worked"], True)

    def test_persistence_and_resume_worked(self):
        self.assertIs(self.result["persistence_resume_worked"], True)

    def test_the_health_check_passed(self):
        self.assertIs(self.result["health_check_passed"], True)

    def test_the_final_capability_lifecycle_state_is_verified_and_not_active(self):
        self.assertEqual(self.result["final_capability_lifecycle_state"], LIFECYCLE_VERIFIED)
        self.assertNotIn("ACTIVE", ALL_LIFECYCLE_STATUSES)

    def test_the_acceptance_run_did_real_work(self):
        # Many checks per stage, not a handful of token assertions.
        self.assertGreater(self.result["checks_run"], 250)

    def test_the_result_is_json_serializable(self):
        self.assertEqual(json.loads(json.dumps(self.result)), self.result)

    def test_two_acceptance_runs_agree(self):
        again = run_final_acceptance()
        for key in ("acceptance_result", "stages_passed", "stages_failed", "detected_issues",
                    "final_capability_lifecycle_state", "checks_run"):
            self.assertEqual(again[key], self.result[key], key)


class AcceptanceFailsClearlyTests(unittest.TestCase):
    """The acceptance test must FAIL, loudly and by name, when the
    system is broken. Each test breaks one existing collaborator on
    purpose (only for the duration of the test) and expects
    SELF_UPGRADE_REQUIRES_FIX naming the right stage."""

    def _assert_requires_fix(self, result, stage, fragment):
        self.assertEqual(result["acceptance_result"], REQUIRES_FIX)
        self.assertIn(stage, result["stages_failed"])
        self.assertTrue(any(f"[{stage}]" in issue and fragment in issue
                            for issue in result["detected_issues"]),
                        f"no issue for [{stage}] mentioning {fragment!r}: "
                        f"{result['detected_issues'][:5]}")
        self.assertIsNot(result["stages_passed"], result["stages_failed"])

    def test_an_inferred_approval_is_detected(self):
        from self_upgrade.capability_approval_manager import ApprovalManager
        real = ApprovalManager.get_stored_record

        def approving_everything(manager, request_id):
            record = real(manager, request_id)
            if record is not None:
                record["status"] = "APPROVED"
            return record

        with mock.patch.object(ApprovalManager, "get_stored_record", approving_everything):
            result = run_final_acceptance()
        self._assert_requires_fix(result, S_APPROVAL_1, "WAIT_FOR_APPROVAL")
        self.assertFalse(result["human_approval_gates_worked"])

    def test_registration_without_the_registration_approval_is_detected(self):
        from self_upgrade import capability_registration_executor as executor
        from self_upgrade.capability_registration_decision import (
            REGISTRATION_DECISION_STATUS_READY)

        def lenient(request_id, approval_manager):
            record = approval_manager.get_stored_record(request_id) or {}
            return {"status": REGISTRATION_DECISION_STATUS_READY,
                    "capability_name": record.get("capability_name"),
                    "registration_plan": record.get("registration_plan"),
                    "source_version": record.get("source_version"), "errors": []}

        with mock.patch.object(executor, "resolve_registration_decision", lenient):
            result = run_final_acceptance()
        self._assert_requires_fix(result, S_APPROVAL_2, "without the registration approval")
        self.assertFalse(result["human_approval_gates_worked"])

    def test_an_automatically_activated_capability_is_detected(self):
        real = CapabilitySystem.register

        def registering_enabled(system, name, description, enabled=False, status="planned"):
            return real(system, name, description, enabled=True, status=status)

        with mock.patch.object(CapabilitySystem, "register", registering_enabled):
            result = run_final_acceptance()
        self._assert_requires_fix(result, S_REGISTRATION, "enabled")

    def test_a_resume_that_restarts_a_completed_stage_is_detected(self):
        from self_upgrade.self_upgrade_lifecycle_coordinator import SelfUpgradeLifecycleCoordinator
        real = SelfUpgradeLifecycleCoordinator.resume

        def restarting(coordinator, context):
            decision = real(coordinator, context)
            if decision is not None:
                decision = dict(decision, decision=DECISION_BUILD)
            return decision

        with mock.patch.object(SelfUpgradeLifecycleCoordinator, "resume", restarting):
            result = run_final_acceptance()
        self._assert_requires_fix(result, S_RESUME, "resume")
        self.assertFalse(result["persistence_resume_worked"])

    def test_a_failing_health_check_is_detected(self):
        with mock.patch.object(SelfUpgradeHealthCheck, "check",
                               return_value={"status": "FAILED", "failed_components": ["analysis"],
                                             "checks_passed": 0, "checks_run": 1,
                                             "live_checked": True, "message": "broken"}):
            result = run_final_acceptance()
        self._assert_requires_fix(result, S_HEALTH, "health check")
        self.assertFalse(result["health_check_passed"])


class AcceptanceIsolationTests(unittest.TestCase):
    """The acceptance run leaves nothing behind and touches nothing else."""

    def test_the_run_touches_no_project_source_or_default_database(self):
        from tests.test_self_upgrade_end_to_end_dry_run import (
            _source_fingerprint, _default_db_fingerprint)
        source, database = _source_fingerprint(), _default_db_fingerprint()
        run_final_acceptance()
        self.assertEqual(_source_fingerprint(), source)
        self.assertEqual(_default_db_fingerprint(), database)

    def test_the_run_leaves_no_temporary_directories_behind(self):
        def leftovers():
            return {n for n in os.listdir(tempfile.gettempdir()) if n.startswith("selfupgrade-e2e-")}
        before = leftovers()
        run_final_acceptance()
        self.assertEqual(leftovers() - before, set())

    def test_the_run_needs_no_network(self):
        with mock.patch("socket.socket", side_effect=AssertionError("network used")):
            self.assertEqual(run_final_acceptance()["acceptance_result"], ACCEPTED)


if __name__ == "__main__":
    print(json.dumps(run_final_acceptance(), indent=2))
