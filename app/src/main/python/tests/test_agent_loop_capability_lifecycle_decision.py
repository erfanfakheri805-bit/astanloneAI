"""
Tests for AgentLoop.get_capability_lifecycle_decision (Prompt 380) -
the AgentLoop-level integration of the existing Prompt 379
CapabilityLifecycleState with the new Prompt 380
CapabilityLifecycleDecision mapping.

This suite focuses on the AgentLoop wrapper itself (a thin
pass-through, exactly like the other Self-Upgrade wrapper methods on
this loop), not on re-testing the derivation/mapping rules already
covered by tests.test_capability_lifecycle and
tests.test_capability_lifecycle_decision.

Covers: PENDING_APPROVAL -> WAITING_FOR_APPROVAL; READY_FOR_REGISTRATION
is reported without registering anything; REGISTERED is reported
without activating or executing anything; VERIFIED is recognized;
BLOCKED/FAILED/ROLLED_BACK stay terminal; calling this method never
registers, activates, or executes a capability; and existing AgentLoop
behavior (other wrapper methods, `run()`) remains unaffected.

Run directly:
    python -m unittest tests.test_agent_loop_capability_lifecycle_decision -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.agent_loop import AgentLoop
from execution.plan_execution_controller import PlanExecutionController
from planning.goal_manager import GoalManager
from planning.plan_manager import PlanManager
from self_upgrade.capability_approval_gate import GATE_STATUS_WAITING_FOR_APPROVAL
from self_upgrade.capability_lifecycle import (
    LIFECYCLE_PENDING_APPROVAL,
    LIFECYCLE_READY_FOR_REGISTRATION,
    LIFECYCLE_REGISTERED,
    LIFECYCLE_VERIFIED,
    LIFECYCLE_BLOCKED,
    LIFECYCLE_FAILED,
    LIFECYCLE_ROLLED_BACK,
)
from self_upgrade.capability_lifecycle_decision import (
    DECISION_WAITING_FOR_APPROVAL,
    DECISION_READY_FOR_REGISTRATION,
    DECISION_VERIFICATION_REQUIRED,
    DECISION_VERIFIED,
    DECISION_BLOCKED,
    DECISION_FAILED,
    DECISION_ROLLED_BACK,
)
from self_upgrade.capability_registration_executor import register_approved_capability
from tests.test_capability_lifecycle import Setup, NAME


def _new_loop():
    goals = GoalManager()
    plans = PlanManager(goals)
    return AgentLoop(goals, plans, PlanExecutionController(plans))


class LoopSetup(Setup):
    def setUp(self):
        super().setUp()
        self.loop = _new_loop()


# --------------------------------------------------------------------
# Rule 1: PENDING_APPROVAL -> WAITING_FOR_APPROVAL
# --------------------------------------------------------------------
class WaitingForApprovalTests(LoopSetup):
    def test_pending_approval_gives_waiting_for_approval(self):
        request = self.registered_request()
        decision = self.loop.get_capability_lifecycle_decision(
            NAME, human_approval_request=request, approval_manager=self.manager)
        self.assertEqual(decision["lifecycle_status"], LIFECYCLE_PENDING_APPROVAL)
        self.assertEqual(decision["decision"], DECISION_WAITING_FOR_APPROVAL)


# --------------------------------------------------------------------
# Rule 2: READY_FOR_REGISTRATION reported, never registered
# --------------------------------------------------------------------
class ReadyForRegistrationTests(LoopSetup):
    def test_ready_for_registration_reported_without_registering(self):
        rows_before = self.capability_system.all()
        approval_request, plan, registration_request = self.chain()
        self.manager.approve(registration_request["request_id"])
        decision = self.loop.get_capability_lifecycle_decision(
            NAME, human_approval_request=approval_request, registration_plan=plan,
            registration_request_id=registration_request["request_id"],
            approval_manager=self.manager)
        self.assertEqual(decision["lifecycle_status"], LIFECYCLE_READY_FOR_REGISTRATION)
        self.assertEqual(decision["decision"], DECISION_READY_FOR_REGISTRATION)
        # The AgentLoop never registers the capability on its own.
        self.assertEqual(self.capability_system.all(), rows_before)


# --------------------------------------------------------------------
# Rule 3: REGISTERED reported, never activated/executed
# --------------------------------------------------------------------
class RegisteredTests(LoopSetup):
    def test_registered_gives_verification_required_and_stays_disabled(self):
        _, _, _, result = self.registered()
        decision = self.loop.get_capability_lifecycle_decision(
            NAME, registration_result=result, approval_manager=self.manager)
        self.assertEqual(decision["lifecycle_status"], LIFECYCLE_REGISTERED)
        self.assertEqual(decision["decision"], DECISION_VERIFICATION_REQUIRED)
        row = next(r for r in self.capability_system.all() if r["name"] == NAME)
        self.assertFalse(row["enabled"])


# --------------------------------------------------------------------
# Rule 4: VERIFIED recognized
# --------------------------------------------------------------------
class VerifiedTests(LoopSetup):
    def test_verified_is_recognized(self):
        _, _, _, result, verification = self.verified()
        decision = self.loop.get_capability_lifecycle_decision(
            NAME, registration_result=result, verification_result=verification,
            approval_manager=self.manager)
        self.assertEqual(decision["lifecycle_status"], LIFECYCLE_VERIFIED)
        self.assertEqual(decision["decision"], DECISION_VERIFIED)


# --------------------------------------------------------------------
# Rule 5: terminal / blocked statuses
# --------------------------------------------------------------------
class TerminalTests(LoopSetup):
    def test_blocked_registration_plan_gives_blocked(self):
        decision = self.loop.get_capability_lifecycle_decision(
            NAME, registration_plan=self.blocked_plan())
        self.assertEqual(decision["lifecycle_status"], LIFECYCLE_BLOCKED)
        self.assertEqual(decision["decision"], DECISION_BLOCKED)

    def test_failing_tests_give_failed(self):
        decision = self.loop.get_capability_lifecycle_decision(
            NAME, build_result=self.build_result(), test_evaluation=self.failing_evaluation())
        self.assertEqual(decision["lifecycle_status"], LIFECYCLE_FAILED)
        self.assertEqual(decision["decision"], DECISION_FAILED)

    def test_completed_rollback_gives_rolled_back(self):
        from agent.code_change_rollback import build_code_change_rollback_decision
        request = self.unstored_human_request()
        rollback = build_code_change_rollback_decision(
            "FAILED", self.path, request["version"], self.versions)
        decision = self.loop.get_capability_lifecycle_decision(
            NAME, test_evaluation=self.failing_evaluation(), rollback_result=rollback)
        self.assertEqual(decision["lifecycle_status"], LIFECYCLE_ROLLED_BACK)
        self.assertEqual(decision["decision"], DECISION_ROLLED_BACK)


# --------------------------------------------------------------------
# The loop never registers, activates, or executes as a side effect
# of inspecting the lifecycle / deciding what is allowed next
# --------------------------------------------------------------------
class NoAutomaticActionTests(LoopSetup):
    def test_no_registration_no_matter_the_status_inspected(self):
        approval_request, plan, registration_request = self.chain()
        self.manager.approve(registration_request["request_id"])
        rows_before = self.capability_system.all()
        self.loop.get_capability_lifecycle_decision(
            NAME, human_approval_request=approval_request, registration_plan=plan,
            registration_request_id=registration_request["request_id"],
            approval_manager=self.manager)
        self.assertEqual(self.capability_system.all(), rows_before)

    def test_no_activation_no_matter_the_status_inspected(self):
        _, _, _, result, verification = self.verified()
        self.loop.get_capability_lifecycle_decision(
            NAME, registration_result=result, verification_result=verification,
            approval_manager=self.manager)
        row = next(r for r in self.capability_system.all() if r["name"] == NAME)
        self.assertFalse(row["enabled"])

    def test_no_execution_capability_handlers_are_never_touched(self):
        # A capability's own execution goes through
        # execution.capability_handlers.CapabilityHandlerRegistry -
        # this loop's plan_execution_controller. Inspecting the
        # lifecycle never touches it.
        controller = self.loop._controller
        handlers_before = list(controller.capability_handlers.registered_names()) \
            if hasattr(controller.capability_handlers, "registered_names") else None
        _, _, _, result, verification = self.verified()
        self.loop.get_capability_lifecycle_decision(
            NAME, registration_result=result, verification_result=verification,
            approval_manager=self.manager)
        if handlers_before is not None:
            self.assertEqual(
                list(controller.capability_handlers.registered_names()), handlers_before)

    def test_approval_manager_is_never_mutated(self):
        request = self.registered_request()
        before = self.manager.get_status(request["request_id"])
        self.loop.get_capability_lifecycle_decision(
            NAME, human_approval_request=request, approval_manager=self.manager)
        after = self.manager.get_status(request["request_id"])
        self.assertEqual(before, after)


# --------------------------------------------------------------------
# Existing AgentLoop behavior remains compatible
# --------------------------------------------------------------------
class CompatibilityTests(LoopSetup):
    def test_existing_self_upgrade_approval_gate_wrapper_still_works(self):
        request = self.approved_request()
        gate_result = self.loop.evaluate_self_upgrade_approval_gate(request, self.manager)
        self.assertNotEqual(gate_result["gate_status"], GATE_STATUS_WAITING_FOR_APPROVAL)

    def test_run_with_no_goal_still_behaves_as_before(self):
        # An AgentLoop with no goals/plans created still fails cleanly
        # on run(), exactly as it always has - this new method changes
        # nothing about that.
        result = self.loop.run("missing-goal", "missing-plan")
        self.assertIn("status", result)

    def test_new_method_does_not_require_the_constructor_to_change(self):
        # get_capability_lifecycle_decision is available on a plain
        # AgentLoop built the exact same way every other test in this
        # project already builds one.
        loop = _new_loop()
        decision = loop.get_capability_lifecycle_decision(NAME)
        self.assertEqual(decision["decision"], "INVALID")  # no evidence supplied at all


if __name__ == "__main__":
    unittest.main()
