"""
Tests for the Self-Upgrade End-to-End Dry Run (Prompt 384) - the first
controlled integration test proving that the EXISTING Self-Upgrade
components work together as one coherent lifecycle:

    SelfUpgradeRequest (357)
      -> AdaptivePlanAnalyzer.analyze_self_upgrade_request (358)
      -> CapabilityCreationPlan (359)
      -> CapabilityImplementationSpec (360)
      -> CapabilityBuildSpec (361)
      -> build_capability (362) / build_capability_apply_request (363)
         [validation] -> apply_capability (364)
      -> run_capability_tests (365) + evaluate_capability_test_result (366)
         [testing]
      -> verify_capability_first_pass (384, the one added hook)
         + request_capability_human_approval (370) [version snapshot]
      -> ApprovalManager.create_request (371)  [GATE 1: human approval]
      -> prepare_capability_registration (373) / plan (374) /
         request_capability_registration_approval (375)
                                                [GATE 2: registration approval]
      -> resolve_registration_decision (376)
      -> register_approved_capability (377)
      -> verify_registered_capability (378)
      -> build_capability_lifecycle_state (379)
      -> SelfUpgradeExecutionContext + Store (382), Resume Manager (383)
      -> SelfUpgradeLifecycleCoordinator (381)

Nothing here is a second Self-Upgrade architecture. `DryRunHarness`
below is only a linear sequence of calls to those existing functions,
folding every result into the existing coordinator's `advance()`; every
decision, status, and gate comes from the existing components. The one
piece of production code added for this prompt is
`self_upgrade.capability_first_pass_verification` (a small adapter, see
its docstring); it is unit-tested at the bottom of this file.

The dry-run capability is a tiny, deterministic, isolated one
(`selfupgrade_dryrun_echo`) that exists only in this test module: its
handler lives in a test-local `CapabilityHandlerRegistry`, the generated
skeleton is written into a temporary workspace, the state lives in a
temporary SQLite file, and the capability is registered only into a
temporary `CapabilitySystem`. The focused test the sandboxed test runner
executes is a static `ast` check - the generated code is never imported
or run - and the registered capability stays disabled ("registered", not
active) throughout.

Covers: the complete successful lifecycle; the first approval gate and
the registration approval gate each independently blocking continuation
(and only an explicit approval lifting each); successful registration
and verification; the final lifecycle state and final references; the
failed-verification path (FAILED, no silent repair, no automatic retry,
never active); no automatic activation and no second Self-Upgrade cycle;
persisted context; resume from an approval gate after a simulated
restart, continuing from the correct stage; test isolation; and the
first-pass verification hook.

Run directly:
    python -m unittest tests.test_self_upgrade_end_to_end_dry_run -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import copy
import hashlib
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

PYTHON_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(PYTHON_ROOT)

from capabilities.capability_system import CapabilitySystem
from execution.capability import Capability
from execution.capability_handlers import CapabilityHandlerRegistry
from memory.memory_system import MemorySystem, _default_db_path
from planning.adaptive_plan_analyzer import AdaptivePlanAnalyzer
from planning.goal_manager import GoalManager
from planning.plan_manager import PlanManager
from self_upgrade.capability_apply_request import build_capability_apply_request
from self_upgrade.capability_approval_gate import (
    evaluate_self_upgrade_approval_gate,
    GATE_STATUS_WAITING_FOR_APPROVAL,
    GATE_STATUS_READY_FOR_ACTIVATION,
)
from self_upgrade.capability_approval_manager import ApprovalManager
from self_upgrade.capability_build_spec import build_capability_build_spec
from self_upgrade.capability_builder import build_capability
from self_upgrade.capability_correction_verification import (
    STATUS_VERIFIED,
    STATUS_INVALID as VERIFICATION_INVALID,
    STATUS_FAILED as VERIFICATION_FAILED,
)
from self_upgrade.capability_creation_plan import build_capability_creation_plan
from self_upgrade.capability_evaluation import evaluate_capability_test_result
from self_upgrade.capability_file_apply import apply_capability
from self_upgrade.capability_first_pass_verification import (
    verify_capability_first_pass,
    VERIFICATION_BASIS_FIRST_PASS,
)
from self_upgrade.capability_human_approval import (
    request_capability_human_approval,
    APPROVAL_STATUS_PENDING,
    APPROVAL_STATUS_APPROVED,
    APPROVAL_STATUS_INVALID,
)
from self_upgrade.capability_implementation_spec import build_capability_implementation_spec
from self_upgrade.capability_lifecycle import (
    build_capability_lifecycle_state,
    ALL_LIFECYCLE_STATUSES,
    LIFECYCLE_VERSIONED,
    LIFECYCLE_PENDING_APPROVAL,
    LIFECYCLE_APPROVED,
    LIFECYCLE_READY_FOR_REGISTRATION,
    LIFECYCLE_REGISTERED,
    LIFECYCLE_VERIFIED,
    LIFECYCLE_FAILED,
)
from self_upgrade.capability_registration_approval import request_capability_registration_approval
from self_upgrade.capability_registration_executor import (
    register_approved_capability,
    REGISTRATION_RESULT_REGISTERED,
    REGISTRATION_RESULT_BLOCKED,
)
from self_upgrade.capability_registration_plan import (
    build_capability_registration_plan,
    PLAN_STATUS_READY_FOR_APPROVED_REGISTRATION,
)
from self_upgrade.capability_registration_preparation import (
    prepare_capability_registration,
    REGISTRATION_STATUS_BLOCKED,
    REGISTRATION_STATUS_READY_FOR_REGISTRATION,
)
from self_upgrade.capability_registration_verifier import (
    verify_registered_capability,
    VERIFICATION_STATUS_VERIFIED,
    VERIFICATION_STATUS_FAILED,
)
from self_upgrade.capability_test_execution import run_capability_tests
from self_upgrade.self_upgrade_execution_context import (
    SelfUpgradeExecutionContextStore,
    CONTEXT_FIELDS,
    validate_execution_context,
)
from self_upgrade.self_upgrade_lifecycle_coordinator import (
    SelfUpgradeLifecycleCoordinator,
    ALL_COORDINATOR_DECISIONS,
    DECISION_ANALYZE,
    DECISION_BUILD,
    DECISION_VALIDATE,
    DECISION_TEST,
    DECISION_VERSION,
    DECISION_WAIT_FOR_APPROVAL,
    DECISION_PREPARE_REGISTRATION,
    DECISION_WAIT_FOR_REGISTRATION_APPROVAL,
    DECISION_REGISTER,
    DECISION_VERIFY_REGISTRATION,
    DECISION_COMPLETED,
    DECISION_FAILED,
)
from self_upgrade.self_upgrade_request import SelfUpgradeRequest
from self_upgrade.self_upgrade_resume_manager import (
    SelfUpgradeResumeManager,
    RESUME_STATUS_RESUMED,
)
from self_upgrade.version_system import VersionSystem

# ----------------------------------------------------------------------
# The tiny, deterministic, isolated dry-run capability
# ----------------------------------------------------------------------
UPGRADE_REQUEST_ID = "upgrade_request-e2e-384"
CAPABILITY_NAME = "selfupgrade_dryrun_echo"
TARGET_MODULE = "selfupgrade_dryrun_echo_module"
TEST_TARGET = "test_selfupgrade_dryrun_echo_module"

# The focused test the existing sandboxed runner executes. Static
# checks only: the generated file is parsed with `ast`, never imported
# or run, so no generated code ever executes during this dry run.
FOCUSED_TEST_SOURCE = '''\
import ast
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SOURCE = os.path.join(HERE, "selfupgrade_dryrun_echo_module.py")


class GeneratedSkeletonStaticTests(unittest.TestCase):
    """Static checks only - the generated file is parsed, never run."""

    def _functions(self):
        with open(SOURCE, encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        return [node for node in tree.body if isinstance(node, ast.FunctionDef)]

    def test_declares_exactly_the_expected_function(self):
        self.assertEqual([f.name for f in self._functions()], ["selfupgrade_dryrun_echo"])

    def test_function_takes_the_declared_input(self):
        (function,) = self._functions()
        self.assertEqual([a.arg for a in function.args.args], ["text"])
'''

# The stage names, in lifecycle order, `DryRunHarness.run_through` walks.
STAGES = (
    "submit_request", "analyze_and_specify", "build", "validate", "apply_and_test",
    "take_snapshot", "submit_for_approval", "approve_first", "prepare_registration",
    "approve_registration", "register", "verify",
)
# The coordinator decision each stage must leave the lifecycle at.
EXPECTED_DECISIONS = {
    "submit_request": DECISION_ANALYZE,
    "analyze_and_specify": DECISION_BUILD,
    "build": DECISION_VALIDATE,
    "validate": DECISION_TEST,
    "apply_and_test": DECISION_VERSION,
    "take_snapshot": DECISION_WAIT_FOR_APPROVAL,
    "submit_for_approval": DECISION_WAIT_FOR_APPROVAL,
    "approve_first": DECISION_PREPARE_REGISTRATION,
    "prepare_registration": DECISION_WAIT_FOR_REGISTRATION_APPROVAL,
    "approve_registration": DECISION_REGISTER,
    "register": DECISION_VERIFY_REGISTRATION,
    "verify": DECISION_COMPLETED,
}


class _HandlerProbe:
    """Records every call to the dry-run capability's handler. The
    dry run must never execute it, so `calls` must stay empty."""

    def __init__(self):
        self.calls = []


def _make_dry_run_capability(probe):
    def handler(data):
        probe.calls.append(dict(data))
        return {"echo": data.get("text", "")}

    # Where the generated skeleton is "intended to live"
    # (`target_module`); resolves to a single file in the temp workspace.
    handler.__module__ = TARGET_MODULE
    return Capability(
        CAPABILITY_NAME, handler,
        description="Deterministic dry-run echo capability (Prompt 384 test only).",
        input_schema={"type": "object",
                      "properties": {"text": {"type": "string", "required": True}}},
        output_schema={"type": "object", "properties": {"echo": {"type": "string"}}},
        metadata={"category": "self_upgrade_dry_run", "test_only": True},
    )


def _source_fingerprint():
    """SHA-256 over every file under the project's python source tree
    (never `__pycache__`): used to prove a run modified no source."""
    digest = hashlib.sha256()
    for directory, subdirs, files in os.walk(PYTHON_ROOT):
        subdirs[:] = sorted(d for d in subdirs if d != "__pycache__")
        for name in sorted(files):
            if name.endswith(".pyc"):
                continue
            path = os.path.join(directory, name)
            digest.update(os.path.relpath(path, PYTHON_ROOT).encode("utf-8"))
            with open(path, "rb") as handle:
                digest.update(handle.read())
    return digest.hexdigest()


def _default_db_fingerprint():
    path = _default_db_path()
    if not os.path.exists(path):
        return None
    stat = os.stat(path)
    return (stat.st_size, stat.st_mtime_ns)


class DryRunHarness:
    """A linear sequence of calls to the EXISTING Self-Upgrade stage
    functions, each result folded into the existing
    `SelfUpgradeLifecycleCoordinator.advance()` and persisted with the
    existing `SelfUpgradeExecutionContextStore`. It decides nothing
    itself: every decision comes from the coordinator, every gate from
    the existing approval components, and every approval is an explicit
    `ApprovalManager.approve()` call the test itself makes."""

    def __init__(self):
        self.root = tempfile.mkdtemp(prefix="selfupgrade-e2e-")
        self.workspace = os.path.join(self.root, "workspace")
        os.makedirs(self.workspace)
        self.db_path = os.path.join(self.root, "state", "e2e.db")

        self.probe = _HandlerProbe()
        self.source_capability = _make_dry_run_capability(self.probe)
        self.handlers = CapabilityHandlerRegistry()
        self.handlers.register_capability(self.source_capability)

        goals = GoalManager()
        self.analyzer = AdaptivePlanAnalyzer(
            goals, PlanManager(goals), capability_system=None,
            capability_handlers=self.handlers)

        self.results = {}      # stage results held in RAM (lost on restart)
        self.evidence = {}     # kwargs handed to every advance()/decide()
        self.decisions = []    # every decision label advance() returned, in order
        self.last_decision = None   # the full decision dict of the latest advance()
        self.context = None
        self._open_services()

    # ---- services (everything a restart throws away and re-opens) -------
    def _open_services(self):
        self.memory = MemorySystem(self.db_path)
        self.versions = VersionSystem(self.memory)
        self.manager = ApprovalManager(self.memory)
        self.capability_system = CapabilitySystem(self.memory)
        self.store = SelfUpgradeExecutionContextStore(self.memory)
        self.coordinator = SelfUpgradeLifecycleCoordinator(self.manager)
        self.resume_manager = SelfUpgradeResumeManager(self.store, self.coordinator)

    def close(self):
        self.memory._conn.close()
        shutil.rmtree(self.root, ignore_errors=True)

    def restart(self):
        """Simulate an application restart: every in-memory object and
        stage result is dropped; only what was persisted (the SQLite
        file and the workspace) survives. The persisted context is then
        loaded again, and everything the next stage needs is taken from
        it and from ApprovalManager alone."""
        self.memory._conn.close()
        self.results, self.evidence, self.decisions, self.context = {}, {}, [], None
        self.last_decision = None
        self._open_services()

        self.context = self.store.load(UPGRADE_REQUEST_ID)
        context = self.context
        self.results["build_spec"] = context["build_spec_reference"]
        approval_id = context["approval_request_id"]
        if approval_id:
            self.evidence["approval_request_id"] = approval_id
            self.results["human_request"] = self._rebuild_human_request(approval_id)
        state = context["current_lifecycle_state"] or {}
        if state.get("registration_request_id"):
            self.evidence["registration_request_id"] = state["registration_request_id"]
            self.results["registration_request_id"] = state["registration_request_id"]

    def _rebuild_human_request(self, approval_id):
        """After a restart the original in-memory HumanApprovalRequest is
        gone. ApprovalManager kept the full record it was submitted as;
        the request dict is only ever *evidence of the snapshot* (its own
        status is never read as a decision - the decision always comes
        from ApprovalManager), so it is rebuilt from that record with its
        status reset to the only status it was ever submitted with."""
        record = self.manager.get_stored_record(approval_id)
        request = {key: value for key, value in record.items() if key != "decision_timestamp"}
        request["status"] = APPROVAL_STATUS_PENDING
        return request

    # ---- folding a result into the coordinator --------------------------
    def advance(self, **extra):
        kwargs = dict(self.evidence)
        kwargs.update(extra)
        self.context, decision = self.coordinator.advance(
            self.context, capability_name=CAPABILITY_NAME,
            approval_manager=self.manager, **kwargs)
        self.store.save(self.context)
        self.decisions.append(decision["decision"])
        self.last_decision = decision
        return decision

    def decide(self):
        """A read-only decision from the evidence gathered so far."""
        return self.coordinator.decide(
            capability_name=CAPABILITY_NAME, approval_manager=self.manager, **self.evidence)

    # ---- the stages, in lifecycle order ---------------------------------
    def submit_request(self):
        request = SelfUpgradeRequest(
            request_id=UPGRADE_REQUEST_ID,
            goal="Add a tiny deterministic echo capability (end-to-end dry run)",
            requested_capability=CAPABILITY_NAME,
            reason="Prompt 384 integration test of the existing Self-Upgrade lifecycle.")
        self.results["request"] = request
        self.context = self.store.get_or_create(UPGRADE_REQUEST_ID, capability_name=CAPABILITY_NAME)
        return self.advance(self_upgrade_request=request)

    def analyze_and_specify(self):
        analysis = self.analyzer.analyze_self_upgrade_request(self.results["request"])
        plan = build_capability_creation_plan(analysis)
        implementation_spec = build_capability_implementation_spec(
            plan, capability_handlers=self.handlers)
        build_spec = build_capability_build_spec(implementation_spec)
        self.results.update(analysis=analysis, creation_plan=plan,
                            implementation_spec=implementation_spec, build_spec=build_spec)
        return self.advance(creation_plan=plan, implementation_spec=implementation_spec,
                            build_spec=build_spec)

    def build(self):
        build_result = build_capability(self.results["build_spec"])
        self.results["build_result"] = build_result
        self.evidence["build_result"] = build_result
        return self.advance()

    def validate(self):
        apply_request = build_capability_apply_request(self.results["build_result"])
        self.results["apply_request"] = apply_request
        self.evidence["apply_request"] = apply_request
        return self.advance()

    def apply_and_test(self):
        applied = apply_capability(
            self.results["apply_request"], self.workspace, allowed_dirs=[self.workspace])
        with open(os.path.join(self.workspace, TEST_TARGET + ".py"), "w", encoding="utf-8") as handle:
            handle.write(FOCUSED_TEST_SOURCE)
        test_result = run_capability_tests(
            applied, self.workspace, TEST_TARGET, allowed_dirs=[self.workspace])
        evaluation = evaluate_capability_test_result(test_result)
        self.results.update(applied=applied, test_result=test_result, evaluation=evaluation)
        self.evidence["test_evaluation"] = evaluation
        return self.advance()

    def take_snapshot(self):
        verification = verify_capability_first_pass(self.results["test_result"])
        human_request = request_capability_human_approval(
            verification, self.versions, allowed_dirs=[self.workspace])
        self.results.update(verification=verification, human_request=human_request)
        self.evidence["human_approval_request"] = human_request
        return self.advance()

    def submit_for_approval(self):
        self.results["approval_created"] = self.manager.create_request(self.results["human_request"])
        self.evidence["approval_request_id"] = self.results["human_request"]["request_id"]
        return self.advance()

    def approve_first(self):
        self.results["first_approval"] = self.manager.approve(
            self.results["human_request"]["request_id"])
        return self.advance()

    def prepare_registration(self):
        preparation = prepare_capability_registration(
            self.results["human_request"], self.manager, self.results["build_spec"])
        plan = build_capability_registration_plan(preparation, approval_manager=self.manager)
        registration_request = request_capability_registration_approval(plan)
        created = self.manager.create_request(registration_request)
        self.results.update(
            preparation=preparation, registration_plan=plan,
            registration_request=registration_request, registration_created=created,
            registration_request_id=registration_request["request_id"])
        self.evidence["registration_plan"] = plan
        self.evidence["registration_request_id"] = registration_request["request_id"]
        return self.advance()

    def approve_registration(self):
        self.results["registration_approval"] = self.manager.approve(
            self.results["registration_request_id"])
        return self.advance()

    def register(self):
        registration_result = register_approved_capability(
            self.results["registration_request_id"], self.manager, self.capability_system)
        self.results["registration_result"] = registration_result
        self.evidence["registration_result"] = registration_result
        return self.advance()

    def verify(self):
        verification_result = verify_registered_capability(
            self.results["registration_result"], self.manager, self.capability_system)
        self.results["verification_result"] = verification_result
        self.evidence["verification_result"] = verification_result
        return self.advance()

    def run_through(self, last_stage):
        """Run every stage up to and including `last_stage`, asserting
        nothing itself (each stage's own decision label is in
        `decisions`). Returns the last full decision dict."""
        for stage in STAGES[:STAGES.index(last_stage) + 1]:
            getattr(self, stage)()
        return self.last_decision

    # ---- reading the outcome --------------------------------------------
    def registry_rows(self):
        return self.capability_system.all()

    def final_lifecycle_state(self):
        r = self.results
        return build_capability_lifecycle_state(
            CAPABILITY_NAME, build_result=r.get("build_result"),
            apply_request=r.get("apply_request"), test_evaluation=r.get("evaluation"),
            human_approval_request=r.get("human_request"), approval_manager=self.manager,
            registration_plan=r.get("registration_plan"),
            registration_request_id=r.get("registration_request_id"),
            registration_result=r.get("registration_result"),
            verification_result=r.get("verification_result"))

    def final_report(self):
        """The final result the prompt asks for, read from the PERSISTED
        context (reloaded from storage) and the final lifecycle state."""
        context = self.store.load(UPGRADE_REQUEST_ID)
        state = self.final_lifecycle_state()
        errors = list(state["errors"])
        if context["last_error"]:
            errors.append(context["last_error"])
        return {
            "upgrade_request_id": context["upgrade_request_id"],
            "capability_name": context["capability_name"],
            "final_lifecycle_state": state["current_status"],
            "version_reference": context["version_reference"],
            "first_approval_reference": context["approval_request_id"],
            "registration_approval_reference":
                (context["current_lifecycle_state"] or {}).get("registration_request_id"),
            "registration_result": context["registration_result_reference"],
            "verification_result": context["verification_result_reference"],
            "execution_context": context,
            "errors": errors,
        }

    def count_state_keys(self, like):
        return len(self.memory.query("SELECT key FROM state WHERE key LIKE ?", (like,)))


class EndToEndBase(unittest.TestCase):
    def setUp(self):
        self.h = DryRunHarness()
        self.addCleanup(self.h.close)

    def assertDecision(self, decision, expected, lifecycle_status=None):
        self.assertEqual(decision["decision"], expected, decision)
        if lifecycle_status is not None:
            self.assertEqual(decision["lifecycle_status"], lifecycle_status, decision)


# ----------------------------------------------------------------------
# The complete successful lifecycle (steps 1-19 of the scenario)
# ----------------------------------------------------------------------
class CompleteSuccessfulLifecycleTests(EndToEndBase):
    def test_complete_successful_lifecycle(self):
        h = self.h
        source_before = _source_fingerprint()

        # 1. A valid SelfUpgradeRequest.
        decision = h.submit_request()
        self.assertTrue(h.results["request"].is_valid())
        self.assertDecision(decision, DECISION_ANALYZE)

        # 2-3. The existing analysis stage, then the creation /
        # implementation / build specifications.
        decision = h.analyze_and_specify()
        self.assertEqual(h.results["analysis"]["blockers"], [])
        self.assertEqual(h.results["creation_plan"]["status"], "READY")
        self.assertEqual(h.results["implementation_spec"]["status"], "READY")
        self.assertEqual(h.results["build_spec"]["status"], "READY")
        self.assertEqual(h.results["build_spec"]["capability_name"], CAPABILITY_NAME)
        self.assertDecision(decision, DECISION_BUILD)

        # 4. The deterministic capability build result.
        decision = h.build()
        self.assertEqual(h.results["build_result"]["status"], "READY")
        self.assertEqual(h.results["build_result"]["code_generation_status"], "GENERATED")
        self.assertDecision(decision, DECISION_VALIDATE)

        # 5. Validation of the generated result.
        decision = h.validate()
        self.assertEqual(h.results["apply_request"]["status"], "READY")
        self.assertEqual(h.results["apply_request"]["validation_result"]["status"], "VALID")
        self.assertDecision(decision, DECISION_TEST)

        # 6. The controlled test stage (existing sandboxed test runner,
        # on the file applied into the temporary workspace only).
        decision = h.apply_and_test()
        self.assertEqual(h.results["applied"]["status"], "APPLIED")
        self.assertTrue(h.results["applied"]["file_path"].startswith(h.workspace))
        self.assertEqual(h.results["test_result"]["status"], "PASSED")
        self.assertEqual(h.results["test_result"]["tests_run"], 2)
        self.assertEqual(h.results["test_result"]["tests_failed"], 0)
        self.assertEqual(h.results["evaluation"]["evaluation_status"], "SUCCESS")
        self.assertDecision(decision, DECISION_VERSION)

        # 7. The version snapshot.
        history_before = len(h.versions.history())
        decision = h.take_snapshot()
        self.assertEqual(h.results["verification"]["status"], STATUS_VERIFIED)
        snapshot_request = h.results["human_request"]
        self.assertEqual(snapshot_request["status"], APPROVAL_STATUS_PENDING)
        self.assertTrue(snapshot_request["rollback_available"])
        self.assertEqual(len(h.versions.history()), history_before + 1)
        self.assertDecision(decision, DECISION_WAIT_FOR_APPROVAL, LIFECYCLE_VERSIONED)

        # 8-9. The human approval request is stored, and the lifecycle
        # stops at the approval gate.
        decision = h.submit_for_approval()
        approval_id = snapshot_request["request_id"]
        self.assertEqual(h.results["approval_created"]["status"], APPROVAL_STATUS_PENDING)
        self.assertDecision(decision, DECISION_WAIT_FOR_APPROVAL, LIFECYCLE_PENDING_APPROVAL)
        self.assertEqual(h.manager.get_status(approval_id)["status"], APPROVAL_STATUS_PENDING)
        # ... and nothing continues while it is pending.
        blocked = prepare_capability_registration(snapshot_request, h.manager, h.results["build_spec"])
        self.assertEqual(blocked["status"], REGISTRATION_STATUS_BLOCKED)
        self.assertDecision(h.decide(), DECISION_WAIT_FOR_APPROVAL, LIFECYCLE_PENDING_APPROVAL)
        self.assertEqual(h.registry_rows(), [])

        # 10. Explicit approval (made by the test itself, nothing inferred).
        decision = h.approve_first()
        self.assertEqual(h.results["first_approval"]["status"], APPROVAL_STATUS_APPROVED)
        self.assertDecision(decision, DECISION_PREPARE_REGISTRATION, LIFECYCLE_APPROVED)

        # 11-13. Registration preparation, the registration approval
        # request, and the lifecycle stopping again.
        decision = h.prepare_registration()
        self.assertEqual(h.results["preparation"]["status"], REGISTRATION_STATUS_READY_FOR_REGISTRATION)
        self.assertEqual(h.results["registration_plan"]["status"], PLAN_STATUS_READY_FOR_APPROVED_REGISTRATION)
        self.assertEqual(h.results["registration_created"]["status"], APPROVAL_STATUS_PENDING)
        registration_id = h.results["registration_request_id"]
        self.assertNotEqual(registration_id, approval_id)
        self.assertDecision(decision, DECISION_WAIT_FOR_REGISTRATION_APPROVAL)
        blocked = register_approved_capability(registration_id, h.manager, h.capability_system)
        self.assertEqual(blocked["status"], REGISTRATION_RESULT_BLOCKED)
        self.assertEqual(h.registry_rows(), [])

        # 14. Explicit registration approval.
        decision = h.approve_registration()
        self.assertEqual(h.results["registration_approval"]["status"], APPROVAL_STATUS_APPROVED)
        self.assertDecision(decision, DECISION_REGISTER, LIFECYCLE_READY_FOR_REGISTRATION)
        self.assertEqual(h.registry_rows(), [])   # approved, still not registered

        # 15. Registration of the isolated test capability.
        decision = h.register()
        self.assertEqual(h.results["registration_result"]["status"], REGISTRATION_RESULT_REGISTERED)
        self.assertDecision(decision, DECISION_VERIFY_REGISTRATION, LIFECYCLE_REGISTERED)
        (row,) = h.registry_rows()
        self.assertEqual(row["name"], CAPABILITY_NAME)

        # 16. Verification of the registration.
        decision = h.verify()
        self.assertEqual(h.results["verification_result"]["status"], VERIFICATION_STATUS_VERIFIED)
        self.assertEqual(h.results["verification_result"]["mismatches"], [])
        self.assertDecision(decision, DECISION_COMPLETED, LIFECYCLE_VERIFIED)

        # 17. The final SelfUpgradeExecutionContext is persisted.
        persisted = h.store.load(UPGRADE_REQUEST_ID)
        self.assertEqual(persisted, h.context)
        self.assertEqual(validate_execution_context(persisted), [])
        self.assertEqual(persisted["current_action"], DECISION_COMPLETED)
        self.assertIsNone(persisted["last_error"])
        self.assertEqual(set(persisted), set(CONTEXT_FIELDS))

        # 18-19. The final CapabilityLifecycleState reaches the existing
        # verified/completed state - and VERIFIED is not ACTIVE.
        state = h.final_lifecycle_state()
        self.assertEqual(state["current_status"], LIFECYCLE_VERIFIED)
        self.assertEqual(state["errors"], [])
        self.assertEqual(persisted["current_lifecycle_state"], state)
        self.assertEqual(h.decisions, [EXPECTED_DECISIONS[stage] for stage in STAGES])
        self.assertEqual(h.registry_rows()[0]["enabled"], 0)

        # The final result, with every reference the prompt asks for.
        report = h.final_report()
        self.assertEqual(report["upgrade_request_id"], UPGRADE_REQUEST_ID)
        self.assertEqual(report["capability_name"], CAPABILITY_NAME)
        self.assertEqual(report["final_lifecycle_state"], LIFECYCLE_VERIFIED)
        self.assertEqual(report["version_reference"]["id"], snapshot_request["version"]["id"])
        self.assertEqual(report["first_approval_reference"], approval_id)
        self.assertEqual(report["registration_approval_reference"], registration_id)
        self.assertEqual(report["registration_result"]["status"], REGISTRATION_RESULT_REGISTERED)
        self.assertEqual(report["verification_result"]["status"], VERIFICATION_STATUS_VERIFIED)
        self.assertEqual(report["execution_context"], persisted)
        self.assertEqual(report["errors"], [])

        # The whole run modified no project source.
        self.assertEqual(_source_fingerprint(), source_before)

    def test_every_stage_reports_the_next_valid_lifecycle_action(self):
        for stage in STAGES:
            with self.subTest(stage=stage):
                getattr(self.h, stage)()
                self.assertEqual(self.h.decisions[-1], EXPECTED_DECISIONS[stage])
                self.assertIn(self.h.decisions[-1], ALL_COORDINATOR_DECISIONS)
                self.assertIsNone(self.h.context["last_error"])


# ----------------------------------------------------------------------
# The two approval gates
# ----------------------------------------------------------------------
class FirstApprovalGateTests(EndToEndBase):
    def setUp(self):
        super().setUp()
        self.decision = self.h.run_through("submit_for_approval")
        self.approval_id = self.h.results["human_request"]["request_id"]

    def test_pending_approval_blocks_continuation(self):
        self.assertDecision(self.decision, DECISION_WAIT_FOR_APPROVAL, LIFECYCLE_PENDING_APPROVAL)
        self.assertEqual(self.h.manager.get_status(self.approval_id)["status"], APPROVAL_STATUS_PENDING)

        gate = evaluate_self_upgrade_approval_gate(self.h.results["human_request"], self.h.manager)
        self.assertEqual(gate["gate_status"], GATE_STATUS_WAITING_FOR_APPROVAL)
        self.assertFalse(gate["registration_allowed"])
        self.assertFalse(gate["activation_allowed"])

        prepared = prepare_capability_registration(
            self.h.results["human_request"], self.h.manager, self.h.results["build_spec"])
        self.assertEqual(prepared["status"], REGISTRATION_STATUS_BLOCKED)
        self.assertIsNone(prepared["target_module"])

    def test_deciding_again_never_infers_approval(self):
        for _ in range(3):
            self.assertDecision(self.h.decide(), DECISION_WAIT_FOR_APPROVAL, LIFECYCLE_PENDING_APPROVAL)
        # Even folding the same evidence into the context again cannot
        # move past the gate.
        self.assertDecision(self.h.advance(), DECISION_WAIT_FOR_APPROVAL, LIFECYCLE_PENDING_APPROVAL)
        self.assertEqual(self.h.manager.get_status(self.approval_id)["status"], APPROVAL_STATUS_PENDING)

    def test_no_registration_or_second_approval_exists_while_pending(self):
        self.assertEqual(self.h.registry_rows(), [])
        self.assertEqual(self.h.count_state_keys("capability_approval:%"), 1)

    def test_only_an_explicit_approval_lifts_the_gate(self):
        gate_before = evaluate_self_upgrade_approval_gate(self.h.results["human_request"], self.h.manager)
        self.assertEqual(gate_before["gate_status"], GATE_STATUS_WAITING_FOR_APPROVAL)

        decision = self.h.approve_first()

        gate_after = evaluate_self_upgrade_approval_gate(self.h.results["human_request"], self.h.manager)
        self.assertEqual(gate_after["gate_status"], GATE_STATUS_READY_FOR_ACTIVATION)
        self.assertDecision(decision, DECISION_PREPARE_REGISTRATION, LIFECYCLE_APPROVED)
        prepared = prepare_capability_registration(
            self.h.results["human_request"], self.h.manager, self.h.results["build_spec"])
        self.assertEqual(prepared["status"], REGISTRATION_STATUS_READY_FOR_REGISTRATION)


class RegistrationApprovalGateTests(EndToEndBase):
    def setUp(self):
        super().setUp()
        self.decision = self.h.run_through("prepare_registration")
        self.approval_id = self.h.results["human_request"]["request_id"]
        self.registration_id = self.h.results["registration_request_id"]

    def test_registration_approval_pending_blocks_continuation(self):
        self.assertDecision(self.decision, DECISION_WAIT_FOR_REGISTRATION_APPROVAL)
        self.assertEqual(self.h.manager.get_status(self.registration_id)["status"], APPROVAL_STATUS_PENDING)

        blocked = register_approved_capability(
            self.registration_id, self.h.manager, self.h.capability_system)
        self.assertEqual(blocked["status"], REGISTRATION_RESULT_BLOCKED)
        self.assertIsNone(blocked["capability"])
        self.assertEqual(self.h.registry_rows(), [])

    def test_first_approval_does_not_authorise_registration(self):
        # The first gate is already APPROVED, yet it is a different,
        # independent request: it can never stand in for the second.
        self.assertEqual(self.h.manager.get_status(self.approval_id)["status"], APPROVAL_STATUS_APPROVED)
        misused = register_approved_capability(
            self.approval_id, self.h.manager, self.h.capability_system)
        self.assertNotEqual(misused["status"], REGISTRATION_RESULT_REGISTERED)
        self.assertEqual(self.h.registry_rows(), [])
        self.assertDecision(self.h.decide(), DECISION_WAIT_FOR_REGISTRATION_APPROVAL)

    def test_deciding_again_never_infers_registration_approval(self):
        for _ in range(3):
            self.assertDecision(self.h.decide(), DECISION_WAIT_FOR_REGISTRATION_APPROVAL)
        self.assertDecision(self.h.advance(), DECISION_WAIT_FOR_REGISTRATION_APPROVAL)
        self.assertEqual(self.h.manager.get_status(self.registration_id)["status"], APPROVAL_STATUS_PENDING)
        self.assertEqual(self.h.registry_rows(), [])

    def test_only_an_explicit_second_approval_allows_registration(self):
        decision = self.h.approve_registration()
        self.assertDecision(decision, DECISION_REGISTER, LIFECYCLE_READY_FOR_REGISTRATION)
        self.assertEqual(self.h.registry_rows(), [])   # approving is not registering

        self.h.register()
        self.assertEqual(self.h.results["registration_result"]["status"], REGISTRATION_RESULT_REGISTERED)
        self.assertEqual(len(self.h.registry_rows()), 1)


# ----------------------------------------------------------------------
# Registration, verification, final state, final references
# ----------------------------------------------------------------------
class RegistrationAndVerificationTests(EndToEndBase):
    def setUp(self):
        super().setUp()
        self.h.run_through("verify")

    def test_successful_registration(self):
        result = self.h.results["registration_result"]
        self.assertEqual(result["status"], REGISTRATION_RESULT_REGISTERED)
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["capability_name"], CAPABILITY_NAME)
        self.assertEqual(result["target_module"], TARGET_MODULE)
        self.assertEqual(result["request_id"], self.h.results["registration_request_id"])
        self.assertEqual(result["approval_request_id"], self.h.results["human_request"]["request_id"])
        (row,) = self.h.registry_rows()
        self.assertEqual(row["name"], CAPABILITY_NAME)
        self.assertEqual(row["status"], "registered")

    def test_successful_verification(self):
        result = self.h.results["verification_result"]
        self.assertEqual(result["status"], VERIFICATION_STATUS_VERIFIED)
        self.assertEqual(result["mismatches"], [])
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["capability_name"], CAPABILITY_NAME)
        self.assertEqual(result["request_id"], self.h.results["registration_request_id"])

    def test_final_lifecycle_state_is_verified_and_not_active(self):
        state = self.h.final_lifecycle_state()
        self.assertEqual(state["current_status"], LIFECYCLE_VERIFIED)
        self.assertEqual(self.h.decisions[-1], DECISION_COMPLETED)
        self.assertNotIn("ACTIVE", ALL_LIFECYCLE_STATUSES)
        self.assertNotIn("ACTIVE", ALL_COORDINATOR_DECISIONS)
        self.assertNotEqual(state["current_status"], "ACTIVE")
        self.assertIn("does not mean the capability is active", state["reason"])

    def test_final_references_are_preserved_in_the_persisted_context(self):
        results = self.h.results
        context = self.h.store.load(UPGRADE_REQUEST_ID)

        self.assertEqual(context["upgrade_request_id"], UPGRADE_REQUEST_ID)
        self.assertEqual(context["capability_name"], CAPABILITY_NAME)
        # The actual stage objects, not re-derived copies.
        self.assertEqual(context["build_spec_reference"], results["build_spec"])
        self.assertEqual(context["implementation_spec_reference"], results["implementation_spec"])
        self.assertEqual(context["version_reference"]["id"], results["human_request"]["version"]["id"])
        self.assertEqual(context["approval_request_id"], results["human_request"]["request_id"])
        self.assertEqual(context["registration_plan_reference"]["approval_request_id"],
                         results["human_request"]["request_id"])
        self.assertEqual(context["registration_result_reference"]["request_id"],
                         results["registration_request_id"])
        self.assertEqual(context["registration_result_reference"]["status"], REGISTRATION_RESULT_REGISTERED)
        self.assertEqual(context["verification_result_reference"]["status"], VERIFICATION_STATUS_VERIFIED)
        self.assertEqual(context["current_lifecycle_state"]["registration_request_id"],
                         results["registration_request_id"])

    def test_final_report_shows_every_required_field(self):
        report = self.h.final_report()
        self.assertEqual(set(report), {
            "upgrade_request_id", "capability_name", "final_lifecycle_state",
            "version_reference", "first_approval_reference", "registration_approval_reference",
            "registration_result", "verification_result", "execution_context", "errors"})
        for key, value in report.items():
            if key != "errors":
                self.assertIsNotNone(value, key)
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["final_lifecycle_state"], LIFECYCLE_VERIFIED)
        self.assertNotEqual(report["first_approval_reference"], report["registration_approval_reference"])


# ----------------------------------------------------------------------
# Persisted context
# ----------------------------------------------------------------------
class PersistedContextTests(EndToEndBase):
    def test_context_is_persisted_after_every_stage(self):
        for stage in STAGES:
            with self.subTest(stage=stage):
                getattr(self.h, stage)()
                persisted = self.h.store.load(UPGRADE_REQUEST_ID)
                self.assertEqual(persisted, self.h.context)
                self.assertEqual(persisted["current_action"], EXPECTED_DECISIONS[stage])
                self.assertEqual(validate_execution_context(persisted), [])

    def test_context_survives_reopening_the_same_database_file(self):
        self.h.run_through("submit_for_approval")
        before = copy.deepcopy(self.h.context)
        self.h.restart()
        self.assertEqual(self.h.context, before)

    def test_exactly_one_context_exists_for_the_request(self):
        self.h.run_through("verify")
        self.assertEqual(self.h.count_state_keys("self_upgrade_execution_context:%"), 1)

    def test_last_completed_action_trails_current_action(self):
        self.h.run_through("build")
        self.assertEqual(self.h.context["current_action"], DECISION_VALIDATE)
        self.assertEqual(self.h.context["last_completed_action"], DECISION_BUILD)


# ----------------------------------------------------------------------
# The failed verification path
# ----------------------------------------------------------------------
class FailedVerificationPathTests(EndToEndBase):
    TAMPERED = "Capability 'selfupgrade_dryrun_echo' silently changed after registration."

    def _register_then_tamper(self):
        self.h.run_through("register")
        self.assertDecision(self.h.last_decision, DECISION_VERIFY_REGISTRATION, LIFECYCLE_REGISTERED)
        # The smallest deterministic failure: the registry row's
        # description drifts away from the approved registration.
        self.h.memory._run("UPDATE capabilities SET description = ? WHERE name = ?",
                           (self.TAMPERED, CAPABILITY_NAME))

    def test_failed_verification_makes_the_lifecycle_failed(self):
        self._register_then_tamper()
        decision = self.h.verify()

        result = self.h.results["verification_result"]
        self.assertEqual(result["status"], VERIFICATION_STATUS_FAILED)
        self.assertTrue(result["mismatches"])
        self.assertDecision(decision, DECISION_FAILED, LIFECYCLE_FAILED)
        self.assertTrue(decision["errors"])
        self.assertEqual(self.h.final_lifecycle_state()["current_status"], LIFECYCLE_FAILED)

        persisted = self.h.store.load(UPGRADE_REQUEST_ID)
        self.assertEqual(persisted["current_action"], DECISION_FAILED)
        self.assertEqual(persisted["current_lifecycle_state"]["current_status"], LIFECYCLE_FAILED)
        self.assertEqual(persisted["verification_result_reference"]["status"], VERIFICATION_STATUS_FAILED)
        report = self.h.final_report()
        self.assertEqual(report["final_lifecycle_state"], LIFECYCLE_FAILED)
        self.assertTrue(report["errors"])

    def test_failed_verification_is_never_repaired_retried_or_activated(self):
        self._register_then_tamper()
        approvals_before = {
            key: self.h.manager.get_stored_record(key)
            for key in (self.h.results["human_request"]["request_id"],
                        self.h.results["registration_request_id"])}
        versions_before = len(self.h.versions.history())
        row_before = self.h.registry_rows()

        with mock.patch.object(CapabilitySystem, "register") as register, \
                mock.patch.object(CapabilitySystem, "set_enabled") as set_enabled, \
                mock.patch.object(ApprovalManager, "approve") as approve, \
                mock.patch.object(ApprovalManager, "reject") as reject, \
                mock.patch.object(ApprovalManager, "create_request") as create_request, \
                mock.patch.object(VersionSystem, "create_version") as create_version:
            self.h.verify()
            for _ in range(3):   # deciding again is deterministic, never a retry
                self.assertDecision(self.h.decide(), DECISION_FAILED, LIFECYCLE_FAILED)
            self.h.advance()

        for spy in (register, set_enabled, approve, reject, create_request, create_version):
            spy.assert_not_called()

        # The drifted row is exactly as it was: not repaired, not
        # re-registered, not replaced, not enabled.
        (row,) = self.h.registry_rows()
        self.assertEqual(row, row_before[0])
        self.assertEqual(row["description"], self.TAMPERED)
        self.assertEqual(row["enabled"], 0)
        self.assertEqual(row["status"], "registered")
        # Approval decisions and snapshots are untouched.
        for key, record in approvals_before.items():
            self.assertEqual(self.h.manager.get_stored_record(key), record)
        self.assertEqual(len(self.h.versions.history()), versions_before)
        self.assertEqual(self.h.decisions.count(DECISION_FAILED), 2)
        self.assertNotIn(DECISION_COMPLETED, self.h.decisions)

    def test_failed_verification_does_not_run_registration_again(self):
        self._register_then_tamper()
        # Prompt 558: patch the module object this test is actually
        # executing in (`sys.modules[__name__]`) rather than a hardcoded
        # "tests.<module>" string. Depending on how the suite is invoked
        # (`python -m unittest tests.X` vs. `unittest discover -s tests`),
        # this file can be imported under two different module names
        # ("tests.test_self_upgrade_end_to_end_dry_run" vs. the flat
        # "test_self_upgrade_end_to_end_dry_run"); a hardcoded dotted
        # string only ever patches the former, so under discovery it can
        # silently create and patch an unrelated second copy of this
        # module while the harness keeps calling the original. Patching
        # `sys.modules[__name__]` always resolves to the module that is
        # actually running, regardless of how it was imported.
        with mock.patch.object(sys.modules[__name__], "register_approved_capability",
                        wraps=register_approved_capability) as register_spy:
            self.h.verify()
            self.h.advance()
        register_spy.assert_not_called()
        self.assertEqual(len(self.h.registry_rows()), 1)
        self.assertEqual(self.h.registry_rows()[0]["description"], self.TAMPERED)

    def test_a_failed_lifecycle_never_reaches_completed(self):
        self._register_then_tamper()
        self.h.verify()
        self.assertNotEqual(self.h.final_lifecycle_state()["current_status"], LIFECYCLE_VERIFIED)
        self.assertNotEqual(self.h.decide()["decision"], DECISION_COMPLETED)
        self.assertNotEqual(self.h.context["current_action"], DECISION_COMPLETED)


# ----------------------------------------------------------------------
# No automatic activation, no second Self-Upgrade cycle
# ----------------------------------------------------------------------
class NoAutomaticActivationTests(EndToEndBase):
    def test_the_registered_capability_is_never_enabled_or_executed(self):
        with mock.patch.object(CapabilitySystem, "set_enabled") as set_enabled:
            self.h.run_through("verify")
            self.h.decide()
            self.h.advance()
        set_enabled.assert_not_called()

        (row,) = self.h.registry_rows()
        self.assertEqual(row["enabled"], 0)
        self.assertEqual(row["status"], "registered")
        self.assertNotIn(row["status"], ("active", "enabled"))
        # The handler never ran, and the generated module was never imported.
        self.assertEqual(self.h.probe.calls, [])
        self.assertNotIn(TARGET_MODULE, sys.modules)
        # The test-local handler registry still holds only the original
        # source capability object - nothing was registered or replaced.
        self.assertIs(self.h.handlers.get_capability(CAPABILITY_NAME), self.h.source_capability)
        self.assertEqual(len(self.h.handlers), 1)

    def test_completing_does_not_start_another_self_upgrade_cycle(self):
        self.h.run_through("verify")
        versions_before = len(self.h.versions.history())
        for _ in range(3):
            self.assertDecision(self.h.decide(), DECISION_COMPLETED, LIFECYCLE_VERIFIED)
        self.assertEqual(len(self.h.versions.history()), versions_before)
        self.assertEqual(self.h.count_state_keys("self_upgrade_execution_context:%"), 1)
        self.assertEqual(self.h.count_state_keys("capability_approval:%"), 2)   # the two gates
        self.assertEqual(len(self.h.registry_rows()), 1)
        self.assertEqual(self.h.decisions.count(DECISION_ANALYZE), 1)
        self.assertEqual(self.h.decisions.count(DECISION_BUILD), 1)

    def test_no_stage_runs_twice_in_a_successful_lifecycle(self):
        # Prompt 558: see the comment in
        # test_failed_verification_does_not_run_registration_again for why
        # this patches `sys.modules[__name__]` rather than a hardcoded
        # "tests.<module>" string - the latter silently patched a second,
        # unused copy of this module under `unittest discover`, so these
        # spies always read back 0 calls no matter what the lifecycle
        # actually did.
        this_module = sys.modules[__name__]
        with mock.patch.object(this_module, "build_capability",
                        wraps=build_capability) as build_spy, \
                mock.patch.object(this_module, "run_capability_tests",
                           wraps=run_capability_tests) as tests_spy, \
                mock.patch.object(this_module, "register_approved_capability",
                           wraps=register_approved_capability) as register_spy, \
                mock.patch.object(this_module, "verify_registered_capability",
                           wraps=verify_registered_capability) as verify_spy:
            self.h.run_through("verify")
        for spy in (build_spy, tests_spy, register_spy, verify_spy):
            self.assertEqual(spy.call_count, 1)


# ----------------------------------------------------------------------
# Resume from an approval gate after a simulated restart
# ----------------------------------------------------------------------
class ResumeFromApprovalGateTests(EndToEndBase):
    def test_resume_at_the_first_gate_waits_then_continues_from_the_correct_stage(self):
        h = self.h
        h.run_through("submit_for_approval")
        approval_id = h.results["human_request"]["request_id"]
        persisted_before = copy.deepcopy(h.store.load(UPGRADE_REQUEST_ID))
        self.assertEqual(persisted_before["current_action"], DECISION_WAIT_FOR_APPROVAL)

        # --- restart: nothing but the database file and workspace survive
        h.restart()
        self.assertEqual(h.results.keys(), {"build_spec", "human_request"})

        # Resume: the persisted context still says "waiting for approval".
        resumed = h.resume_manager.resume(UPGRADE_REQUEST_ID)
        self.assertEqual(resumed["resume_status"], RESUME_STATUS_RESUMED)
        self.assertDecision(resumed["decision"], DECISION_WAIT_FOR_APPROVAL, LIFECYCLE_PENDING_APPROVAL)
        self.assertEqual(resumed["errors"], [])
        # Resuming is read-only and idempotent.
        self.assertEqual(h.resume_manager.resume(UPGRADE_REQUEST_ID), resumed)
        self.assertEqual(h.store.load(UPGRADE_REQUEST_ID), persisted_before)

        # It remains waiting - re-derived fresh from ApprovalManager, and
        # the existing components still refuse to continue.
        self.assertEqual(h.manager.get_status(approval_id)["status"], APPROVAL_STATUS_PENDING)
        self.assertDecision(h.decide(), DECISION_WAIT_FOR_APPROVAL, LIFECYCLE_PENDING_APPROVAL)
        blocked = prepare_capability_registration(
            h.results["human_request"], h.manager, h.results["build_spec"])
        self.assertEqual(blocked["status"], REGISTRATION_STATUS_BLOCKED)

        # Explicit approval, then continue from the correct stage.
        versions_before = len(h.versions.history())
        approvals_before = h.count_state_keys("capability_approval:%")
        decision = h.approve_first()
        self.assertDecision(decision, DECISION_PREPARE_REGISTRATION, LIFECYCLE_APPROVED)
        self.assertEqual(h.context["last_completed_action"], DECISION_WAIT_FOR_APPROVAL)

        # ... without restarting the process: no re-analysis, rebuild,
        # retest, new snapshot, or second approval request.
        self.assertEqual(h.decisions, [DECISION_PREPARE_REGISTRATION])
        self.assertEqual(len(h.versions.history()), versions_before)
        self.assertEqual(h.count_state_keys("capability_approval:%"), approvals_before)
        self.assertEqual(h.context["build_spec_reference"], persisted_before["build_spec_reference"])
        self.assertEqual(h.context["implementation_spec_reference"],
                         persisted_before["implementation_spec_reference"])
        self.assertEqual(h.context["created_at"], persisted_before["created_at"])
        self.assertEqual(h.registry_rows(), [])

        # The rest of the lifecycle completes from where it left off.
        for stage in STAGES[STAGES.index("prepare_registration"):]:
            getattr(h, stage)()
        self.assertEqual(h.decisions[1:], [EXPECTED_DECISIONS[s] for s in
                                          STAGES[STAGES.index("prepare_registration"):]])
        self.assertEqual(h.decisions[-1], DECISION_COMPLETED)
        self.assertEqual(h.registry_rows()[0]["enabled"], 0)

        # Final references survive the restart unchanged.
        report = h.final_report()
        self.assertEqual(report["final_lifecycle_state"], LIFECYCLE_VERIFIED)
        self.assertEqual(report["first_approval_reference"], approval_id)
        self.assertEqual(report["version_reference"], persisted_before["version_reference"])
        self.assertEqual(report["registration_result"]["status"], REGISTRATION_RESULT_REGISTERED)
        self.assertEqual(report["verification_result"]["status"], VERIFICATION_STATUS_VERIFIED)
        self.assertEqual(report["errors"], [])
        self.assertEqual(h.count_state_keys("self_upgrade_execution_context:%"), 1)

    def test_resume_at_the_registration_gate_waits_then_continues_from_the_correct_stage(self):
        h = self.h
        h.run_through("prepare_registration")
        registration_id = h.results["registration_request_id"]
        persisted_before = copy.deepcopy(h.store.load(UPGRADE_REQUEST_ID))
        self.assertEqual(persisted_before["current_action"], DECISION_WAIT_FOR_REGISTRATION_APPROVAL)

        h.restart()

        resumed = h.resume_manager.resume(UPGRADE_REQUEST_ID)
        self.assertEqual(resumed["resume_status"], RESUME_STATUS_RESUMED)
        self.assertDecision(resumed["decision"], DECISION_WAIT_FOR_REGISTRATION_APPROVAL)
        self.assertEqual(h.store.load(UPGRADE_REQUEST_ID), persisted_before)
        self.assertEqual(h.manager.get_status(registration_id)["status"], APPROVAL_STATUS_PENDING)
        self.assertDecision(h.decide(), DECISION_WAIT_FOR_REGISTRATION_APPROVAL)
        blocked = register_approved_capability(registration_id, h.manager, h.capability_system)
        self.assertEqual(blocked["status"], REGISTRATION_RESULT_BLOCKED)
        self.assertEqual(h.registry_rows(), [])

        decision = h.approve_registration()
        self.assertDecision(decision, DECISION_REGISTER, LIFECYCLE_READY_FOR_REGISTRATION)
        self.assertEqual(h.context["last_completed_action"], DECISION_WAIT_FOR_REGISTRATION_APPROVAL)
        self.assertEqual(h.registry_rows(), [])

        h.register()
        h.verify()
        self.assertEqual(h.decisions, [DECISION_REGISTER, DECISION_VERIFY_REGISTRATION, DECISION_COMPLETED])
        report = h.final_report()
        self.assertEqual(report["final_lifecycle_state"], LIFECYCLE_VERIFIED)
        self.assertEqual(report["registration_approval_reference"], registration_id)
        self.assertEqual(report["version_reference"], persisted_before["version_reference"])
        self.assertEqual(report["first_approval_reference"], persisted_before["approval_request_id"])
        self.assertEqual(h.registry_rows()[0]["enabled"], 0)


# ----------------------------------------------------------------------
# Test isolation
# ----------------------------------------------------------------------
class IsolationTests(EndToEndBase):
    def test_a_full_run_touches_no_project_source_or_default_database(self):
        source_before = _source_fingerprint()
        default_db_before = _default_db_fingerprint()
        self.h.run_through("verify")
        self.assertEqual(_source_fingerprint(), source_before)
        self.assertEqual(_default_db_fingerprint(), default_db_before)

    def test_every_written_file_stays_inside_the_temporary_root(self):
        self.h.run_through("verify")
        applied = os.path.realpath(self.h.results["applied"]["file_path"])
        self.assertTrue(applied.startswith(os.path.realpath(self.h.workspace) + os.sep))
        self.assertTrue(os.path.realpath(self.h.db_path).startswith(os.path.realpath(self.h.root)))
        self.assertFalse(os.path.exists(os.path.join(PYTHON_ROOT, TARGET_MODULE + ".py")))
        self.assertFalse(os.path.exists(os.path.join(PYTHON_ROOT, TEST_TARGET + ".py")))
        self.assertEqual(sorted(os.listdir(self.h.workspace)),
                         sorted([TARGET_MODULE + ".py", TEST_TARGET + ".py"]))

    def test_the_run_needs_no_network(self):
        with mock.patch("socket.socket", side_effect=AssertionError("network access attempted")):
            self.h.run_through("verify")
        self.assertEqual(self.h.decisions[-1], DECISION_COMPLETED)

    def test_the_run_needs_no_api_key_or_external_ai_service(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.h.run_through("verify")
        self.assertEqual(self.h.decisions[-1], DECISION_COMPLETED)

    def test_the_dry_run_capability_is_not_in_any_production_registry(self):
        production_names = {row["name"] for row in CapabilitySystem(
            MemorySystem(os.path.join(self.h.root, "fresh", "fresh.db"))).all()}
        self.assertNotIn(CAPABILITY_NAME, production_names)
        self.assertEqual(self.h.registry_rows(), [])
        self.h.run_through("verify")
        self.assertEqual([row["name"] for row in self.h.registry_rows()], [CAPABILITY_NAME])

    def test_two_runs_do_not_share_state(self):
        self.h.run_through("verify")
        other = DryRunHarness()
        self.addCleanup(other.close)
        self.assertIsNone(other.store.load(UPGRADE_REQUEST_ID))
        self.assertEqual(other.registry_rows(), [])
        self.assertNotEqual(self.h.root, other.root)


# ----------------------------------------------------------------------
# The one production hook added for this prompt
# ----------------------------------------------------------------------
class FirstPassVerificationHookTests(unittest.TestCase):
    def passed_result(self, **overrides):
        result = {
            "capability_name": CAPABILITY_NAME, "file_path": "/tmp/ws/module.py",
            "status": "PASSED", "tests_run": 2, "tests_passed": 2, "tests_failed": 0,
            "execution_time": 0.1, "output": "", "errors": [], "timeout_seconds": 30,
        }
        result.update(overrides)
        return result

    def test_a_passed_first_run_is_verified(self):
        verification = verify_capability_first_pass(self.passed_result())
        self.assertEqual(verification["status"], STATUS_VERIFIED)
        self.assertEqual(verification["errors"], [])
        self.assertEqual(verification["capability_name"], CAPABILITY_NAME)
        self.assertEqual(verification["file_path"], "/tmp/ws/module.py")
        self.assertEqual(verification["retest_result"]["tests_passed"], 2)
        self.assertEqual(verification["retest_evaluation"]["evaluation_status"], "SUCCESS")
        self.assertEqual(verification["verification_basis"], VERIFICATION_BASIS_FIRST_PASS)

    def test_it_records_that_no_correction_was_applied(self):
        verification = verify_capability_first_pass(self.passed_result())
        self.assertFalse(verification["correction_verified"])
        self.assertFalse(verification["improved"])
        self.assertIsNone(verification["correction_apply_result"])
        self.assertIsNone(verification["previous_test_result"])
        self.assertIsNone(verification["previous_evaluation"])

    def test_it_has_every_key_of_a_correction_verification_result(self):
        from self_upgrade.capability_correction_verification import _result as correction_result
        reference = correction_result(STATUS_VERIFIED, {"capability_name": "x", "file_path": "y"}, {})
        verification = verify_capability_first_pass(self.passed_result())
        self.assertEqual(set(verification) - {"verification_basis"}, set(reference))

    def test_a_failed_first_run_is_not_verified(self):
        failed = self.passed_result(status="FAILED", tests_passed=1, tests_failed=1,
                                    errors=["AssertionError"])
        verification = verify_capability_first_pass(failed)
        self.assertNotEqual(verification["status"], STATUS_VERIFIED)
        self.assertEqual(verification["status"], VERIFICATION_FAILED)
        self.assertTrue(verification["errors"])

    def test_timeout_blocked_and_invalid_first_runs_are_not_verified(self):
        for status in ("TIMEOUT", "BLOCKED", "INVALID"):
            with self.subTest(status=status):
                verification = verify_capability_first_pass(self.passed_result(
                    status=status, tests_run=None, tests_passed=None, tests_failed=None,
                    errors=["reason"]))
                self.assertNotEqual(verification["status"], STATUS_VERIFIED)
                self.assertTrue(verification["errors"])

    def test_an_inconsistent_passed_result_is_not_verified(self):
        verification = verify_capability_first_pass(self.passed_result(tests_failed=1))
        self.assertNotEqual(verification["status"], STATUS_VERIFIED)

    def test_a_verified_result_needs_a_capability_name_and_file_path(self):
        for key in ("capability_name", "file_path"):
            with self.subTest(missing=key):
                verification = verify_capability_first_pass(self.passed_result(**{key: "  "}))
                self.assertEqual(verification["status"], VERIFICATION_INVALID)
                self.assertTrue(verification["errors"])

    def test_malformed_input_is_invalid_and_never_raises(self):
        for bad in (None, "PASSED", 42, [], {}, {"status": "PASSED"}):
            with self.subTest(bad=bad):
                verification = verify_capability_first_pass(bad)
                self.assertEqual(verification["status"], VERIFICATION_INVALID)
                self.assertTrue(verification["errors"])
                self.assertFalse(verification["correction_verified"])

    def test_it_never_mutates_its_input(self):
        result = self.passed_result()
        before = copy.deepcopy(result)
        verify_capability_first_pass(result)
        self.assertEqual(result, before)

    def test_it_runs_nothing_and_touches_no_file(self):
        with mock.patch("subprocess.run", side_effect=AssertionError("ran a process")), \
                mock.patch("builtins.open", side_effect=AssertionError("opened a file")):
            self.assertEqual(verify_capability_first_pass(self.passed_result())["status"],
                             STATUS_VERIFIED)

    def test_only_a_verified_first_pass_reaches_a_snapshot(self):
        sandbox = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(sandbox, ignore_errors=True))
        path = os.path.join(sandbox, "module.py")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("def f():\n    return 1\n")
        memory = MemorySystem(os.path.join(sandbox, "state", "hook.db"))
        self.addCleanup(memory._conn.close)
        versions = VersionSystem(memory)
        history_before = len(versions.history())

        failed = verify_capability_first_pass(self.passed_result(
            file_path=path, status="FAILED", tests_passed=1, tests_failed=1, errors=["boom"]))
        refused = request_capability_human_approval(failed, versions, allowed_dirs=[sandbox])
        self.assertEqual(refused["status"], APPROVAL_STATUS_INVALID)
        self.assertEqual(len(versions.history()), history_before)   # no snapshot

        passed = verify_capability_first_pass(self.passed_result(file_path=path))
        accepted = request_capability_human_approval(passed, versions, allowed_dirs=[sandbox])
        self.assertEqual(accepted["status"], APPROVAL_STATUS_PENDING)
        self.assertEqual(len(versions.history()), history_before + 1)
        self.assertEqual(accepted["tests_passed"], 2)


if __name__ == "__main__":
    unittest.main()
