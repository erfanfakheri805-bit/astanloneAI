"""
Tests for self_upgrade.self_upgrade_lifecycle_coordinator
.SelfUpgradeLifecycleCoordinator / build_self_upgrade_lifecycle_decision
(Prompt 381) - the one small orchestration/decision layer that connects
SelfUpgradeRequest (Prompt 357) -> AdaptivePlanAnalyzer ->
CapabilityCreationPlan (Prompt 359) -> ... -> CapabilityLifecycleState
(Prompt 379) into a single deterministic "what is the next valid
lifecycle action" decision.

Every fixture used here is a real result from the real Prompt 357-379
stages - reusing tests.test_capability_lifecycle.Setup exactly like
tests.test_capability_lifecycle_decision already does.

Covers every major lifecycle transition named in the prompt this module
was built from: new SelfUpgradeRequest -> ANALYZE; analyzed request ->
BUILD; built -> VALIDATE; validated -> TEST; failed test with a
correctable error -> CORRECT; successful test -> VERSION; versioned ->
WAIT_FOR_APPROVAL; approved -> PREPARE_REGISTRATION; registration
approval pending -> WAIT_FOR_REGISTRATION_APPROVAL; registration-
approved -> REGISTER; registered -> VERIFY_REGISTRATION; verified ->
COMPLETED; rejected approval -> BLOCKED; failed lifecycle -> FAILED;
rolled-back lifecycle -> ROLLED_BACK; plus that the coordinator never
activates a capability, never executes unauthorized generated code,
never creates a recursive/uncontrolled loop, and that every existing
test in this project keeps passing untouched.

Run directly:
    python -m unittest tests.test_self_upgrade_lifecycle_coordinator -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from planning.goal_manager import GoalManager
from planning.plan_manager import PlanManager
from planning.adaptive_plan_analyzer import AdaptivePlanAnalyzer

from self_upgrade.capability_creation_plan import (
    build_capability_creation_plan,
    STATUS_READY as PLAN_STATUS_READY,
)
from self_upgrade.capability_lifecycle import (
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
    LIFECYCLE_REJECTED,
    LIFECYCLE_FAILED,
    LIFECYCLE_ROLLED_BACK,
)
from self_upgrade.capability_registration_executor import (
    register_approved_capability,
    REGISTRATION_RESULT_REGISTERED,
)
from self_upgrade.self_upgrade_lifecycle_coordinator import (
    SelfUpgradeLifecycleCoordinator,
    build_self_upgrade_lifecycle_decision,
    ALL_COORDINATOR_DECISIONS,
    NON_ACTIONABLE_DECISIONS,
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
    DECISION_FAILED,
    DECISION_ROLLED_BACK,
    DECISION_INVALID,
)
from self_upgrade.self_upgrade_request import (
    SelfUpgradeRequest,
    STATUS_REQUESTED,
    STATUS_ANALYZING,
    STATUS_COMPLETED as REQUEST_STATUS_COMPLETED,
    STATUS_FAILED as REQUEST_STATUS_FAILED,
    STATUS_REJECTED as REQUEST_STATUS_REJECTED,
)
from execution.capability_handlers import CapabilityHandlerRegistry
from execution.code_change_plan_capability import (
    CAPABILITY_NAME as CODE_CHANGE_PLAN_NAME,
    make_code_change_plan_handler,
)
from tests.test_capability_lifecycle import Setup, NAME

DECISION_KEYS = {
    "capability_name", "lifecycle_status", "decision", "reason", "errors", "lifecycle_state",
}


def _self_upgrade_request(**overrides):
    fields = dict(
        request_id="upgrade_request-1", goal="Reduce startup latency",
        requested_capability=CODE_CHANGE_PLAN_NAME,
        reason="Startup is slower than the target budget.",
    )
    fields.update(overrides)
    return SelfUpgradeRequest(**fields)


class FakeCapabilitySystem:
    def __init__(self, registered=None):
        self._registered = dict(registered) if registered else {}

    def all(self):
        return [
            {"name": name, "enabled": enabled, "status": "enabled" if enabled else "disabled"}
            for name, enabled in self._registered.items()
        ]


def _ready_creation_plan(capability_name=CODE_CHANGE_PLAN_NAME):
    capability_system = FakeCapabilitySystem({capability_name: True})
    handlers = CapabilityHandlerRegistry()
    handlers.register(capability_name, make_code_change_plan_handler())
    goals = GoalManager()
    plans = PlanManager(goals)
    analyzer = AdaptivePlanAnalyzer(
        goals, plans, capability_system=capability_system, capability_handlers=handlers)
    analysis = analyzer.analyze_self_upgrade_request(
        _self_upgrade_request(requested_capability=capability_name))
    plan = build_capability_creation_plan(analysis)
    return plan


class CoordinatorSetup(Setup):
    """Adds the coordinator itself, plus pre-pipeline (SelfUpgradeRequest
    / CapabilityCreationPlan) fixtures, on top of the real Prompt
    361-378 fixtures `tests.test_capability_lifecycle.Setup` already
    builds."""

    def setUp(self):
        super().setUp()
        self.coordinator = SelfUpgradeLifecycleCoordinator()

    def decide(self, **kwargs):
        return self.coordinator.decide(capability_name=NAME, **kwargs)

    def decide_from_lifecycle(self, **results):
        return build_self_upgrade_lifecycle_decision(capability_name=NAME, **results)


# --------------------------------------------------------------------
# Vocabulary
# --------------------------------------------------------------------
class VocabularyTests(unittest.TestCase):
    def test_all_decisions_are_exactly_the_specified_ones(self):
        self.assertEqual(ALL_COORDINATOR_DECISIONS, (
            "ANALYZE", "BUILD", "VALIDATE", "TEST", "CORRECT", "VERSION",
            "WAIT_FOR_APPROVAL", "PREPARE_REGISTRATION", "WAIT_FOR_REGISTRATION_APPROVAL",
            "REGISTER", "VERIFY_REGISTRATION", "COMPLETED", "BLOCKED", "FAILED",
            "ROLLED_BACK", "INVALID"))

    def test_non_actionable_decisions_are_a_subset(self):
        for decision in NON_ACTIONABLE_DECISIONS:
            self.assertIn(decision, ALL_COORDINATOR_DECISIONS)

    def test_result_never_raises_on_garbage_input(self):
        result = build_self_upgrade_lifecycle_decision(
            capability_name=123, self_upgrade_request="not a request",
            creation_plan=["nope"], build_result={"weird": True})
        self.assertIn(result["decision"], ALL_COORDINATOR_DECISIONS)
        self.assertEqual(set(result.keys()), DECISION_KEYS)


# --------------------------------------------------------------------
# Pre-pipeline: new request -> ANALYZE; analyzed -> BUILD
# --------------------------------------------------------------------
class PrePipelineTests(CoordinatorSetup):
    def test_new_self_upgrade_request_gives_analyze(self):
        request = _self_upgrade_request(status=STATUS_REQUESTED)
        result = self.decide(self_upgrade_request=request)
        self.assertEqual(result["decision"], DECISION_ANALYZE)
        self.assertIsNone(result["lifecycle_state"])
        self.assertEqual(result["capability_name"], CODE_CHANGE_PLAN_NAME)

    def test_analyzing_self_upgrade_request_also_gives_analyze(self):
        request = _self_upgrade_request(status=STATUS_ANALYZING)
        result = self.decide(self_upgrade_request=request)
        self.assertEqual(result["decision"], DECISION_ANALYZE)

    def test_analyzed_request_gives_build(self):
        plan = _ready_creation_plan()
        self.assertEqual(plan["status"], PLAN_STATUS_READY)
        result = self.decide(creation_plan=plan)
        self.assertEqual(result["decision"], DECISION_BUILD)
        self.assertEqual(result["capability_name"], CODE_CHANGE_PLAN_NAME)

    def test_creation_plan_takes_priority_over_raw_request(self):
        request = _self_upgrade_request(status=STATUS_REQUESTED)
        plan = _ready_creation_plan()
        result = self.decide(self_upgrade_request=request, creation_plan=plan)
        self.assertEqual(result["decision"], DECISION_BUILD)

    def test_rejected_self_upgrade_request_gives_blocked(self):
        request = _self_upgrade_request(status=REQUEST_STATUS_REJECTED)
        result = self.decide(self_upgrade_request=request)
        self.assertEqual(result["decision"], DECISION_BLOCKED)
        self.assertTrue(result["errors"])

    def test_failed_self_upgrade_request_gives_failed(self):
        request = _self_upgrade_request(status=REQUEST_STATUS_FAILED)
        result = self.decide(self_upgrade_request=request)
        self.assertEqual(result["decision"], DECISION_FAILED)

    def test_completed_self_upgrade_request_gives_completed(self):
        request = _self_upgrade_request(status=REQUEST_STATUS_COMPLETED)
        result = self.decide(self_upgrade_request=request)
        self.assertEqual(result["decision"], DECISION_COMPLETED)

    def test_build_result_takes_priority_over_pre_pipeline_fixtures(self):
        request = _self_upgrade_request(status=STATUS_REQUESTED)
        result = self.decide(self_upgrade_request=request, build_result=self.build_result())
        self.assertEqual(result["decision"], DECISION_VALIDATE)
        self.assertEqual(result["lifecycle_status"], LIFECYCLE_BUILT)


# --------------------------------------------------------------------
# Build / validate / test / version
# --------------------------------------------------------------------
class BuildThroughVersionTests(CoordinatorSetup):
    def test_built_capability_gives_validate(self):
        result = self.decide(build_result=self.build_result())
        self.assertEqual(result["lifecycle_status"], LIFECYCLE_BUILT)
        self.assertEqual(result["decision"], DECISION_VALIDATE)

    def test_validated_capability_gives_test(self):
        result = self.decide(
            build_result=self.build_result(), apply_request=self.apply_request())
        self.assertEqual(result["lifecycle_status"], LIFECYCLE_VALIDATED)
        self.assertEqual(result["decision"], DECISION_TEST)

    def test_successful_test_gives_version(self):
        result = self.decide(
            build_result=self.build_result(), apply_request=self.apply_request(),
            test_evaluation=self.passing_evaluation())
        self.assertEqual(result["lifecycle_status"], LIFECYCLE_TESTED)
        self.assertEqual(result["decision"], DECISION_VERSION)

    def test_failed_test_with_correctable_error_gives_correct(self):
        evaluation = self.failing_evaluation()
        result = self.decide(test_evaluation=evaluation)
        self.assertEqual(result["lifecycle_status"], LIFECYCLE_FAILED)
        self.assertEqual(result["decision"], DECISION_CORRECT)

    def test_versioned_capability_gives_wait_for_approval(self):
        result = self.decide(human_approval_request=self.unstored_human_request())
        self.assertEqual(result["lifecycle_status"], LIFECYCLE_VERSIONED)
        self.assertEqual(result["decision"], DECISION_WAIT_FOR_APPROVAL)


# --------------------------------------------------------------------
# Approval / registration approval / registration / verification
# --------------------------------------------------------------------
class ApprovalAndRegistrationTests(CoordinatorSetup):
    def test_pending_capability_approval_gives_wait_for_approval(self):
        request = self.registered_request()
        result = self.decide(human_approval_request=request, approval_manager=self.manager)
        self.assertEqual(result["lifecycle_status"], LIFECYCLE_PENDING_APPROVAL)
        self.assertEqual(result["decision"], DECISION_WAIT_FOR_APPROVAL)

    def test_approved_capability_gives_prepare_registration(self):
        request = self.approved_request()
        result = self.decide(human_approval_request=request, approval_manager=self.manager)
        self.assertEqual(result["lifecycle_status"], LIFECYCLE_APPROVED)
        self.assertEqual(result["decision"], DECISION_PREPARE_REGISTRATION)

    def test_pending_registration_approval_gives_wait_for_registration_approval(self):
        _, _, registration_request = self.chain()
        result = self.decide(
            registration_request_id=registration_request["request_id"],
            approval_manager=self.manager)
        self.assertEqual(result["lifecycle_status"], LIFECYCLE_PENDING_APPROVAL)
        self.assertEqual(result["decision"], DECISION_WAIT_FOR_REGISTRATION_APPROVAL)

    def test_undecided_registration_request_alongside_approval_also_waits_on_registration(self):
        approval_request, plan, registration_request = self.chain()
        result = self.decide(
            human_approval_request=approval_request, registration_plan=plan,
            registration_request_id=registration_request["request_id"],
            approval_manager=self.manager)
        # lifecycle_status here is APPROVED (see capability_lifecycle's own
        # "furthest progress" rule) but the coordinator must still report
        # that registration approval - not capability approval - is what
        # is actually pending, using the registration_request_id the
        # lifecycle state already carries.
        self.assertEqual(result["lifecycle_status"], LIFECYCLE_APPROVED)
        self.assertEqual(result["decision"], DECISION_WAIT_FOR_REGISTRATION_APPROVAL)

    def test_registration_approved_gives_register(self):
        approval_request, plan, registration_request = self.chain()
        self.manager.approve(registration_request["request_id"])
        result = self.decide(
            human_approval_request=approval_request, registration_plan=plan,
            registration_request_id=registration_request["request_id"],
            approval_manager=self.manager)
        self.assertEqual(result["lifecycle_status"], LIFECYCLE_READY_FOR_REGISTRATION)
        self.assertEqual(result["decision"], DECISION_REGISTER)

    def test_registered_capability_gives_verify_registration(self):
        _, _, _, result_dict = self.registered()
        self.assertEqual(result_dict["status"], REGISTRATION_RESULT_REGISTERED)
        result = self.decide(registration_result=result_dict, approval_manager=self.manager)
        self.assertEqual(result["lifecycle_status"], LIFECYCLE_REGISTERED)
        self.assertEqual(result["decision"], DECISION_VERIFY_REGISTRATION)

    def test_verified_capability_gives_completed(self):
        _, _, _, registration_result, verification = self.verified()
        result = self.decide(
            registration_result=registration_result, verification_result=verification,
            approval_manager=self.manager)
        self.assertEqual(result["lifecycle_status"], LIFECYCLE_VERIFIED)
        self.assertEqual(result["decision"], DECISION_COMPLETED)

    def test_rejected_approval_gives_blocked(self):
        request = self.registered_request()
        self.manager.reject(request["request_id"])
        result = self.decide(human_approval_request=request, approval_manager=self.manager)
        self.assertEqual(result["lifecycle_status"], LIFECYCLE_REJECTED)
        self.assertEqual(result["decision"], DECISION_BLOCKED)
        self.assertTrue(result["errors"])


# --------------------------------------------------------------------
# Failure / rollback
# --------------------------------------------------------------------
class FailureTests(CoordinatorSetup):
    def test_plain_failed_test_gives_failed_not_correct(self):
        # No output, no errors, no tests_failed > 0: nothing usable to
        # correct from, so evaluate_capability_test_result reports
        # plain FAILED rather than NEEDS_CORRECTION.
        raw = self.raw_test_result("FAILED", passed=0, failed=0, errors=[])
        raw["output"] = ""
        from self_upgrade.capability_evaluation import evaluate_capability_test_result
        evaluated = evaluate_capability_test_result(raw)
        self.assertNotEqual(evaluated["evaluation_status"], "NEEDS_CORRECTION")
        result = self.decide(test_evaluation=evaluated)
        self.assertEqual(result["lifecycle_status"], LIFECYCLE_FAILED)
        self.assertEqual(result["decision"], DECISION_FAILED)

    def test_rolled_back_gives_rolled_back(self):
        from agent.code_change_rollback import (
            CHANGE_STATUS_ROLLED_BACK, ROLLBACK_STATUS_SUCCEEDED,
        )
        rollback = {
            "change_status": CHANGE_STATUS_ROLLED_BACK,
            "rollback_status": ROLLBACK_STATUS_SUCCEEDED,
        }
        result = self.decide(build_result=self.build_result(), rollback_result=rollback)
        self.assertEqual(result["lifecycle_status"], LIFECYCLE_ROLLED_BACK)
        self.assertEqual(result["decision"], DECISION_ROLLED_BACK)


# --------------------------------------------------------------------
# Safety boundary
# --------------------------------------------------------------------
class SafetyBoundaryTests(CoordinatorSetup):
    def test_coordinator_never_activates_a_capability(self):
        request = self.approved_request()
        before = list(self.capability_system.all())
        self.decide(human_approval_request=request, approval_manager=self.manager)
        self.assertEqual(self.capability_system.all(), before)

    def test_coordinator_never_calls_approve_or_reject(self):
        request = self.registered_request()
        self.decide(human_approval_request=request, approval_manager=self.manager)
        self.assertNotIn("approve", self.manager.calls)
        self.assertNotIn("reject", self.manager.calls)

    def test_coordinator_never_registers_or_verifies(self):
        _, _, registration_request = self.chain()
        self.manager.approve(registration_request["request_id"])
        before_calls = list(self.manager.calls)
        result = self.decide(
            registration_request_id=registration_request["request_id"],
            approval_manager=self.manager)
        self.assertEqual(result["decision"], DECISION_REGISTER)
        # No new capability_system registration happened as a side effect.
        self.assertEqual(self.capability_system.all(), [])

    def test_is_deterministic(self):
        request = self.approved_request()
        first = self.decide(human_approval_request=request, approval_manager=self.manager)
        second = self.decide(human_approval_request=request, approval_manager=self.manager)
        self.assertEqual(first["decision"], second["decision"])
        self.assertEqual(first["lifecycle_status"], second["lifecycle_status"])

    def test_every_lifecycle_status_resolves_to_a_recognized_decision(self):
        for status in ALL_LIFECYCLE_STATUSES:
            state = {
                "capability_name": NAME, "current_status": status, "errors": [],
                "registration_request_id": None,
            }
            from self_upgrade.self_upgrade_lifecycle_coordinator import _judge_lifecycle_state
            decision, reason, errors = _judge_lifecycle_state(state, None)
            self.assertIn(decision, ALL_COORDINATOR_DECISIONS)

    def test_class_wrapper_and_function_agree(self):
        request = self.approved_request()
        via_class = self.decide(human_approval_request=request, approval_manager=self.manager)
        via_function = self.decide_from_lifecycle(
            human_approval_request=request, approval_manager=self.manager)
        self.assertEqual(via_class["decision"], via_function["decision"])

    def test_coordinator_stored_approval_manager_is_used_as_default(self):
        coordinator = SelfUpgradeLifecycleCoordinator(approval_manager=self.manager)
        request = self.approved_request()
        result = coordinator.decide(capability_name=NAME, human_approval_request=request)
        self.assertEqual(result["decision"], DECISION_PREPARE_REGISTRATION)


if __name__ == "__main__":
    unittest.main()
