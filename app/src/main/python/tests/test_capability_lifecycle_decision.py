"""
Tests for self_upgrade.capability_lifecycle_decision
.build_capability_lifecycle_decision (Prompt 380) - the one, fixed
mapping from an already-derived CapabilityLifecycleState (Prompt 379)
onto the structured decision AgentLoop is allowed to report about a
capability's Self-Upgrade lifecycle.

Every lifecycle_state used here is a real one produced by the real
`self_upgrade.capability_lifecycle.build_capability_lifecycle_state`
(Prompt 379) - reusing the exact same fixtures
tests.test_capability_lifecycle.Setup already builds from the real
Prompt 361-378 stages.

Covers: PENDING_APPROVAL -> WAITING_FOR_APPROVAL; APPROVED ->
REGISTRATION_REQUIRED (never registers); READY_FOR_REGISTRATION ->
READY_FOR_REGISTRATION (never registers); REGISTERED ->
VERIFICATION_REQUIRED (never activates/executes); VERIFIED -> VERIFIED;
BLOCKED / REJECTED -> BLOCKED; FAILED -> FAILED; ROLLED_BACK ->
ROLLED_BACK; the early BUILT/VALIDATED/TESTED/VERSIONED progress
states -> CONTINUE_BUILD; INVALID / malformed input -> INVALID; that
every recognized lifecycle status maps to exactly one decision and the
mapping never raises; and that deciding never activates, executes,
approves, registers, or otherwise modifies anything.

Run directly:
    python -m unittest tests.test_capability_lifecycle_decision -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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
    LIFECYCLE_INVALID,
    LIFECYCLE_BLOCKED,
    LIFECYCLE_REJECTED,
    LIFECYCLE_FAILED,
    LIFECYCLE_ROLLED_BACK,
)
from self_upgrade.capability_lifecycle_decision import (
    build_capability_lifecycle_decision,
    ALL_CAPABILITY_DECISIONS,
    DECISION_CONTINUE_BUILD,
    DECISION_WAITING_FOR_APPROVAL,
    DECISION_REGISTRATION_REQUIRED,
    DECISION_READY_FOR_REGISTRATION,
    DECISION_VERIFICATION_REQUIRED,
    DECISION_VERIFIED,
    DECISION_BLOCKED,
    DECISION_FAILED,
    DECISION_ROLLED_BACK,
    DECISION_INVALID,
)
from self_upgrade.capability_registration_executor import (
    register_approved_capability,
    REGISTRATION_RESULT_ALREADY_REGISTERED,
)
from tests.test_capability_lifecycle import Setup, NAME

DECISION_KEYS = {
    "capability_name", "lifecycle_status", "decision", "reason", "errors", "lifecycle_state",
}


class DecideFromSetup(Setup):
    def decide(self, **results):
        return build_capability_lifecycle_decision(self.derive(**results))


# --------------------------------------------------------------------
# Vocabulary
# --------------------------------------------------------------------
class VocabularyTests(unittest.TestCase):
    def test_all_decisions_are_exactly_the_specified_ones(self):
        self.assertEqual(ALL_CAPABILITY_DECISIONS, (
            "CONTINUE_BUILD", "WAITING_FOR_APPROVAL", "REGISTRATION_REQUIRED",
            "READY_FOR_REGISTRATION", "VERIFICATION_REQUIRED", "VERIFIED",
            "BLOCKED", "FAILED", "ROLLED_BACK", "INVALID"))

    def test_every_lifecycle_status_is_mapped_to_exactly_one_decision(self):
        for status in ALL_LIFECYCLE_STATUSES:
            state = {"capability_name": NAME, "current_status": status, "errors": []}
            decision = build_capability_lifecycle_decision(state)
            self.assertIn(decision["decision"], ALL_CAPABILITY_DECISIONS)
            self.assertEqual(decision["lifecycle_status"], status)


# --------------------------------------------------------------------
# Rule 1: PENDING_APPROVAL -> WAITING_FOR_APPROVAL (and only that)
# --------------------------------------------------------------------
class PendingApprovalTests(DecideFromSetup):
    def test_pending_approval_gives_waiting_for_approval(self):
        request = self.registered_request()
        decision = self.decide(human_approval_request=request, approval_manager=self.manager)
        self.assertEqual(decision["lifecycle_status"], LIFECYCLE_PENDING_APPROVAL)
        self.assertEqual(decision["decision"], DECISION_WAITING_FOR_APPROVAL)

    def test_only_pending_approval_produces_waiting_for_approval(self):
        for status in ALL_LIFECYCLE_STATUSES:
            if status == LIFECYCLE_PENDING_APPROVAL:
                continue
            state = {"capability_name": NAME, "current_status": status, "errors": []}
            decision = build_capability_lifecycle_decision(state)
            self.assertNotEqual(decision["decision"], DECISION_WAITING_FOR_APPROVAL, status)


# --------------------------------------------------------------------
# Rule 2: APPROVED / READY_FOR_REGISTRATION never auto-register
# --------------------------------------------------------------------
class ApprovedAndReadyForRegistrationTests(DecideFromSetup):
    def test_approved_gives_registration_required(self):
        request = self.approved_request()
        decision = self.decide(human_approval_request=request, approval_manager=self.manager)
        self.assertEqual(decision["lifecycle_status"], LIFECYCLE_APPROVED)
        self.assertEqual(decision["decision"], DECISION_REGISTRATION_REQUIRED)

    def test_ready_for_registration_gives_ready_for_registration(self):
        approval_request, plan, registration_request = self.chain()
        self.manager.approve(registration_request["request_id"])
        decision = self.decide(
            human_approval_request=approval_request, registration_plan=plan,
            registration_request_id=registration_request["request_id"],
            approval_manager=self.manager)
        self.assertEqual(decision["lifecycle_status"], LIFECYCLE_READY_FOR_REGISTRATION)
        self.assertEqual(decision["decision"], DECISION_READY_FOR_REGISTRATION)

    def test_neither_decision_registers_the_capability(self):
        rows_before = self.capability_system.all()
        approval_request, plan, registration_request = self.chain()
        self.manager.approve(registration_request["request_id"])
        self.decide(
            human_approval_request=approval_request, registration_plan=plan,
            registration_request_id=registration_request["request_id"],
            approval_manager=self.manager)
        self.assertEqual(self.capability_system.all(), rows_before)


# --------------------------------------------------------------------
# Rule 3: REGISTERED never auto-activates/executes
# --------------------------------------------------------------------
class RegisteredTests(DecideFromSetup):
    def test_registered_gives_verification_required(self):
        _, _, _, result = self.registered()
        decision = self.decide(registration_result=result, approval_manager=self.manager)
        self.assertEqual(decision["lifecycle_status"], LIFECYCLE_REGISTERED)
        self.assertEqual(decision["decision"], DECISION_VERIFICATION_REQUIRED)

    def test_registered_capability_stays_disabled(self):
        _, _, _, result = self.registered()
        self.decide(registration_result=result, approval_manager=self.manager)
        row = next(r for r in self.capability_system.all() if r["name"] == NAME)
        self.assertFalse(row["enabled"])

    def test_already_registered_replay_also_gives_verification_required(self):
        _, _, registration_request, result = self.registered()
        replay = register_approved_capability(
            registration_request["request_id"], self.manager, self.capability_system)
        self.assertEqual(replay["status"], REGISTRATION_RESULT_ALREADY_REGISTERED)
        decision = self.decide(registration_result=replay)
        self.assertEqual(decision["decision"], DECISION_VERIFICATION_REQUIRED)


# --------------------------------------------------------------------
# Rule 4: VERIFIED is recognized
# --------------------------------------------------------------------
class VerifiedTests(DecideFromSetup):
    def test_verified_gives_verified(self):
        _, _, _, result, verification = self.verified()
        decision = self.decide(
            registration_result=result, verification_result=verification,
            approval_manager=self.manager)
        self.assertEqual(decision["lifecycle_status"], LIFECYCLE_VERIFIED)
        self.assertEqual(decision["decision"], DECISION_VERIFIED)
        self.assertEqual(decision["errors"], [])

    def test_verified_does_not_enable_the_capability(self):
        _, _, _, result, verification = self.verified()
        self.decide(registration_result=result, verification_result=verification)
        row = next(r for r in self.capability_system.all() if r["name"] == NAME)
        self.assertFalse(row["enabled"])


# --------------------------------------------------------------------
# Rule 5: FAILED, BLOCKED, REJECTED, ROLLED_BACK stay terminal/blocked
# --------------------------------------------------------------------
class TerminalStatusTests(DecideFromSetup):
    def test_blocked_registration_plan_gives_blocked(self):
        decision = self.decide(registration_plan=self.blocked_plan())
        self.assertEqual(decision["lifecycle_status"], LIFECYCLE_BLOCKED)
        self.assertEqual(decision["decision"], DECISION_BLOCKED)

    def test_rejected_capability_approval_gives_blocked(self):
        request = self.registered_request()
        self.manager.reject(request["request_id"])
        decision = self.decide(human_approval_request=request, approval_manager=self.manager)
        self.assertEqual(decision["lifecycle_status"], LIFECYCLE_REJECTED)
        self.assertEqual(decision["decision"], DECISION_BLOCKED)
        self.assertTrue(decision["errors"])

    def test_failing_tests_give_failed(self):
        decision = self.decide(build_result=self.build_result(),
                               test_evaluation=self.failing_evaluation())
        self.assertEqual(decision["lifecycle_status"], LIFECYCLE_FAILED)
        self.assertEqual(decision["decision"], DECISION_FAILED)

    def test_completed_rollback_gives_rolled_back(self):
        request = self.unstored_human_request()
        from agent.code_change_rollback import build_code_change_rollback_decision
        rollback = build_code_change_rollback_decision(
            "FAILED", self.path, request["version"], self.versions)
        self.assertEqual(rollback["change_status"], "ROLLED_BACK")
        decision = self.decide(test_evaluation=self.failing_evaluation(),
                               rollback_result=rollback)
        self.assertEqual(decision["lifecycle_status"], LIFECYCLE_ROLLED_BACK)
        self.assertEqual(decision["decision"], DECISION_ROLLED_BACK)

    def test_rolled_back_and_failed_are_distinct_decisions(self):
        failed = self.decide(test_evaluation=self.failing_evaluation())
        self.assertEqual(failed["decision"], DECISION_FAILED)
        self.assertNotEqual(failed["decision"], DECISION_ROLLED_BACK)


# --------------------------------------------------------------------
# Early progress states
# --------------------------------------------------------------------
class ContinueBuildTests(DecideFromSetup):
    def test_built_gives_continue_build(self):
        decision = self.decide(build_result=self.build_result())
        self.assertEqual(decision["lifecycle_status"], LIFECYCLE_BUILT)
        self.assertEqual(decision["decision"], DECISION_CONTINUE_BUILD)

    def test_validated_tested_versioned_all_give_continue_build(self):
        request = self.unstored_human_request()
        decision = self.decide(
            build_result=self.build_result(), apply_request=self.apply_request(),
            test_evaluation=self.passing_evaluation(), human_approval_request=request)
        self.assertEqual(decision["lifecycle_status"], LIFECYCLE_VERSIONED)
        self.assertEqual(decision["decision"], DECISION_CONTINUE_BUILD)


# --------------------------------------------------------------------
# INVALID / malformed input
# --------------------------------------------------------------------
class InvalidTests(unittest.TestCase):
    def test_invalid_lifecycle_state_gives_invalid(self):
        state = {"capability_name": NAME, "current_status": LIFECYCLE_INVALID, "errors": ["x"]}
        decision = build_capability_lifecycle_decision(state)
        self.assertEqual(decision["decision"], DECISION_INVALID)
        self.assertEqual(decision["errors"], ["x"])

    def test_none_lifecycle_state_gives_invalid_and_never_raises(self):
        decision = build_capability_lifecycle_decision(None)
        self.assertEqual(decision["decision"], DECISION_INVALID)
        self.assertTrue(decision["errors"])

    def test_non_dict_lifecycle_state_gives_invalid_and_never_raises(self):
        decision = build_capability_lifecycle_decision(["not", "a", "dict"])
        self.assertEqual(decision["decision"], DECISION_INVALID)

    def test_unrecognized_status_gives_invalid_and_never_raises(self):
        state = {"capability_name": NAME, "current_status": "NOT_A_REAL_STATUS", "errors": []}
        decision = build_capability_lifecycle_decision(state)
        self.assertEqual(decision["decision"], DECISION_INVALID)
        self.assertTrue(decision["errors"])

    def test_missing_current_status_gives_invalid(self):
        decision = build_capability_lifecycle_decision({"capability_name": NAME})
        self.assertEqual(decision["decision"], DECISION_INVALID)


# --------------------------------------------------------------------
# Shape / no side effects
# --------------------------------------------------------------------
class ShapeAndSafetyTests(DecideFromSetup):
    def test_result_has_exactly_the_documented_keys(self):
        decision = self.decide(build_result=self.build_result())
        self.assertEqual(set(decision.keys()), DECISION_KEYS)

    def test_lifecycle_state_is_carried_through_unchanged(self):
        state = self.derive(build_result=self.build_result())
        decision = build_capability_lifecycle_decision(state)
        self.assertEqual(decision["lifecycle_state"], state)

    def test_capability_name_is_carried_through(self):
        decision = self.decide(build_result=self.build_result())
        self.assertEqual(decision["capability_name"], NAME)

    def test_deciding_never_touches_the_capability_registry(self):
        _, _, _, result, verification = self.verified()
        rows_before = self.capability_system.all()
        self.decide(registration_result=result, verification_result=verification,
                    approval_manager=self.manager)
        self.assertEqual(self.capability_system.all(), rows_before)

    def test_deciding_never_calls_approval_manager_decision_methods(self):
        request = self.registered_request()
        state = self.derive(human_approval_request=request, approval_manager=self.manager)
        self.manager.calls.clear()
        build_capability_lifecycle_decision(state)
        self.assertEqual(self.manager.calls, [])

    def test_repeated_decisions_are_stable(self):
        state = self.derive(build_result=self.build_result())
        first = build_capability_lifecycle_decision(state)
        second = build_capability_lifecycle_decision(state)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
