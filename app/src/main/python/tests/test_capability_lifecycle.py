"""
Tests for self_upgrade.capability_lifecycle
.build_capability_lifecycle_state (Prompt 379) - one small, unified,
read-only lifecycle state for a capability, derived from the results
the existing Self-Upgrade stages already produced:
BUILT -> VALIDATED -> TESTED -> VERSIONED -> PENDING_APPROVAL ->
APPROVED -> READY_FOR_REGISTRATION -> REGISTERED -> VERIFIED, plus the
INVALID / BLOCKED / REJECTED / FAILED / ROLLED_BACK failure states.

Every upstream result used here is a real one produced by the real
Prompt 361-378 stages (never a hand-assembled status dict, except a
PASSED/FAILED raw test result, which the real evaluator then turns
into the CapabilityEvaluation this module reads).

Covers: each progress state; pending / approved / ready-for-
registration / registered / verified; rejected, blocked, failed and
rolled-back states (ROLLED_BACK distinct from FAILED); a registered
capability whose verification failed staying FAILED; a missing
registration or verification result never producing REGISTERED /
VERIFIED; VERIFIED never meaning ACTIVE; and that deriving a state
never executes, activates, approves, registers, or modifies anything.

Run directly:
    python -m unittest tests.test_capability_lifecycle -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import ast
import copy
import os
import sys
import unittest
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.code_change_rollback import build_code_change_rollback_decision
from execution.capability import Capability
from self_upgrade import capability_lifecycle as lifecycle_module
from self_upgrade.capability_apply_request import build_capability_apply_request
from self_upgrade.capability_approval_manager import ApprovalManager
from self_upgrade.capability_builder import build_capability
from self_upgrade.capability_evaluation import evaluate_capability_test_result
from self_upgrade.capability_human_approval import (
    request_capability_human_approval,
    APPROVAL_STATUS_BLOCKED,
    APPROVAL_STATUS_PENDING,
)
from self_upgrade.capability_lifecycle import (
    build_capability_lifecycle_state,
    ALL_LIFECYCLE_STATUSES,
    LIFECYCLE_PROGRESS,
    LIFECYCLE_FAILURE_STATUSES,
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
from self_upgrade.capability_correction_verification import STATUS_VERIFIED
from self_upgrade.capability_registration_approval import (
    request_capability_registration_approval,
)
from self_upgrade.capability_registration_executor import (
    register_approved_capability,
    REGISTRATION_RESULT_REGISTERED,
    REGISTRATION_RESULT_ALREADY_REGISTERED,
    REGISTRATION_RESULT_BLOCKED,
    REGISTRATION_RESULT_FAILED,
)
from self_upgrade.capability_registration_verifier import (
    verify_registered_capability,
    VERIFICATION_STATUS_VERIFIED,
    VERIFICATION_STATUS_FAILED,
)
from tests.test_capability_registration_decision import Setup as DecisionSetup
from tests.test_capability_registration_preparation import CODE_CHANGE_PLAN_NAME

STATE_KEYS = {
    "capability_name", "current_status", "approval_request_id",
    "registration_request_id", "registration_plan", "registration_result",
    "verification_result", "source_version", "reason", "errors",
}
NAME = CODE_CHANGE_PLAN_NAME


class _ReadOnlyApprovalManager(ApprovalManager):
    """Records every call made to it, to prove the lifecycle only ever
    reads approval records."""

    def __init__(self, memory):
        super().__init__(memory)
        self.calls = []

    def get_stored_record(self, request_id):
        self.calls.append("get_stored_record")
        return super().get_stored_record(request_id)

    def create_request(self, *args, **kwargs):
        self.calls.append("create_request")
        return super().create_request(*args, **kwargs)

    def approve(self, *args, **kwargs):
        self.calls.append("approve")
        return super().approve(*args, **kwargs)

    def reject(self, *args, **kwargs):
        self.calls.append("reject")
        return super().reject(*args, **kwargs)


class Setup(DecisionSetup):
    """Real results from the real Prompt 361-378 stages, all for the
    same capability and the same approval chain."""

    def setUp(self):
        super().setUp()
        self.manager = _ReadOnlyApprovalManager(self.memory)

    # ---- early stages -------------------------------------------------
    def build_result(self):
        result = build_capability(self.build_spec)
        self.assertEqual(result["status"], "READY")
        return result

    def apply_request(self):
        request = build_capability_apply_request(self.build_result())
        self.assertEqual(request["status"], "READY")
        return request

    def raw_test_result(self, status="PASSED", passed=3, failed=0, errors=()):
        return {
            "capability_name": NAME, "file_path": self.path, "status": status,
            "tests_run": passed + failed, "tests_passed": passed, "tests_failed": failed,
            "execution_time": 0.1, "output": "ran", "errors": list(errors),
            "timeout_seconds": 30,
        }

    def passing_evaluation(self):
        evaluation = evaluate_capability_test_result(self.raw_test_result())
        self.assertEqual(evaluation["evaluation_status"], "SUCCESS")
        return evaluation

    def failing_evaluation(self):
        evaluation = evaluate_capability_test_result(
            self.raw_test_result("FAILED", passed=2, failed=1, errors=["assertion failed"]))
        self.assertEqual(evaluation["evaluation_status"], "NEEDS_CORRECTION")
        return evaluation

    # ---- versioning / approval ----------------------------------------
    def unstored_human_request(self):
        """A real VersionSystem snapshot + HumanApprovalRequest that has
        NOT been submitted to the ApprovalManager."""
        verification = {
            "status": STATUS_VERIFIED, "capability_name": NAME, "file_path": self.path,
            "retest_result": {"tests_passed": 3, "tests_failed": 0},
        }
        request = request_capability_human_approval(
            verification, self.versions, allowed_dirs=[self.sandbox])
        self.assertEqual(request["status"], APPROVAL_STATUS_PENDING)
        return request

    def blocked_human_request(self):
        verification = {
            "status": STATUS_VERIFIED, "capability_name": NAME,
            "file_path": os.path.join(self.sandbox, "missing.py"),
            "retest_result": {"tests_passed": 3, "tests_failed": 0},
        }
        request = request_capability_human_approval(
            verification, self.versions, allowed_dirs=[self.sandbox])
        self.assertEqual(request["status"], APPROVAL_STATUS_BLOCKED)
        return request

    # ---- the full chain -----------------------------------------------
    def chain(self):
        """(capability approval request [APPROVED], registration plan,
        registration approval request [stored, still PENDING])."""
        approval_request, plan = self.ready_plan()
        registration_request = request_capability_registration_approval(plan)
        created = self.manager.create_request(registration_request)
        self.assertEqual(created["errors"], [])
        return approval_request, plan, registration_request

    def registered(self):
        """A real REGISTERED result, plus the chain that produced it."""
        approval_request, plan, registration_request = self.chain()
        self.manager.approve(registration_request["request_id"])
        result = register_approved_capability(
            registration_request["request_id"], self.manager, self.capability_system)
        self.assertEqual(result["status"], REGISTRATION_RESULT_REGISTERED)
        return approval_request, plan, registration_request, result

    def verified(self):
        approval_request, plan, registration_request, result = self.registered()
        verification = verify_registered_capability(
            result, self.manager, self.capability_system)
        self.assertEqual(verification["status"], VERIFICATION_STATUS_VERIFIED)
        return approval_request, plan, registration_request, result, verification

    # ---- deriving ------------------------------------------------------
    def derive(self, **results):
        return build_capability_lifecycle_state(NAME, **results)

    def assertStatus(self, state, expected):
        self.assertEqual(state["current_status"], expected, state)


# --------------------------------------------------------------------
# Vocabulary
# --------------------------------------------------------------------
class VocabularyTests(unittest.TestCase):
    def test_progress_and_failure_statuses_are_exactly_the_specified_ones(self):
        self.assertEqual(LIFECYCLE_PROGRESS, (
            "BUILT", "VALIDATED", "TESTED", "VERSIONED", "PENDING_APPROVAL",
            "APPROVED", "READY_FOR_REGISTRATION", "REGISTERED", "VERIFIED"))
        self.assertEqual(LIFECYCLE_FAILURE_STATUSES, (
            "INVALID", "BLOCKED", "REJECTED", "FAILED", "ROLLED_BACK"))
        self.assertEqual(ALL_LIFECYCLE_STATUSES,
                         LIFECYCLE_PROGRESS + LIFECYCLE_FAILURE_STATUSES)

    def test_rolled_back_is_distinct_from_failed(self):
        self.assertNotEqual(LIFECYCLE_ROLLED_BACK, LIFECYCLE_FAILED)


# --------------------------------------------------------------------
# Build / validation / test / version
# --------------------------------------------------------------------
class EarlyProgressTests(Setup):
    def test_ready_build_result_is_built(self):
        state = self.derive(build_result=self.build_result())
        self.assertStatus(state, LIFECYCLE_BUILT)
        self.assertEqual(state["errors"], [])

    def test_valid_apply_request_is_validated(self):
        state = self.derive(build_result=self.build_result(),
                            apply_request=self.apply_request())
        self.assertStatus(state, LIFECYCLE_VALIDATED)

    def test_passing_evaluation_is_tested(self):
        state = self.derive(build_result=self.build_result(),
                            apply_request=self.apply_request(),
                            test_evaluation=self.passing_evaluation())
        self.assertStatus(state, LIFECYCLE_TESTED)

    def test_version_snapshot_not_yet_submitted_is_versioned(self):
        request = self.unstored_human_request()
        state = self.derive(
            build_result=self.build_result(), apply_request=self.apply_request(),
            test_evaluation=self.passing_evaluation(),
            human_approval_request=request, approval_manager=self.manager)
        self.assertStatus(state, LIFECYCLE_VERSIONED)
        self.assertEqual(state["source_version"]["id"], request["version"]["id"])
        self.assertEqual(state["approval_request_id"], request["request_id"])

    def test_versioned_without_an_approval_manager(self):
        state = self.derive(human_approval_request=self.unstored_human_request())
        self.assertStatus(state, LIFECYCLE_VERSIONED)


# --------------------------------------------------------------------
# Approval states come from ApprovalManager only
# --------------------------------------------------------------------
class ApprovalStateTests(Setup):
    def test_stored_undecided_request_is_pending_approval(self):
        request = self.registered_request()
        state = self.derive(human_approval_request=request, approval_manager=self.manager)
        self.assertStatus(state, LIFECYCLE_PENDING_APPROVAL)

    def test_explicitly_approved_request_is_approved(self):
        request = self.approved_request()
        state = self.derive(human_approval_request=request, approval_manager=self.manager)
        self.assertStatus(state, LIFECYCLE_APPROVED)
        self.assertEqual(state["approval_request_id"], request["request_id"])

    def test_approval_can_be_derived_from_the_stored_record_alone(self):
        request = self.approved_request()
        state = self.derive(approval_request_id=request["request_id"],
                            approval_manager=self.manager)
        self.assertStatus(state, LIFECYCLE_APPROVED)

    def test_request_dict_claiming_approved_is_never_trusted(self):
        request = self.registered_request()  # stored, still PENDING
        forged = dict(request, status="APPROVED")
        state = self.derive(human_approval_request=forged, approval_manager=self.manager)
        self.assertStatus(state, LIFECYCLE_INVALID)
        self.assertNotEqual(state["current_status"], LIFECYCLE_APPROVED)

    def test_approved_stays_approved_without_registration(self):
        request = self.approved_request()
        state = self.derive(human_approval_request=request, approval_manager=self.manager)
        self.assertNotIn(state["current_status"],
                         (LIFECYCLE_READY_FOR_REGISTRATION, LIFECYCLE_REGISTERED,
                          LIFECYCLE_VERIFIED))

    def test_approved_registration_decision_is_ready_for_registration(self):
        approval_request, plan, registration_request = self.chain()
        self.manager.approve(registration_request["request_id"])
        state = self.derive(
            human_approval_request=approval_request, registration_plan=plan,
            registration_request_id=registration_request["request_id"],
            approval_manager=self.manager)
        self.assertStatus(state, LIFECYCLE_READY_FOR_REGISTRATION)
        self.assertEqual(state["registration_request_id"], registration_request["request_id"])
        self.assertEqual(state["registration_plan"]["capability_name"], NAME)
        self.assertEqual(state["errors"], [])

    def test_undecided_registration_request_does_not_go_past_approved(self):
        approval_request, plan, registration_request = self.chain()
        state = self.derive(
            human_approval_request=approval_request, registration_plan=plan,
            registration_request_id=registration_request["request_id"],
            approval_manager=self.manager)
        self.assertStatus(state, LIFECYCLE_APPROVED)

    def test_undecided_registration_request_alone_is_pending_approval(self):
        _, _, registration_request = self.chain()
        state = self.derive(registration_request_id=registration_request["request_id"],
                            approval_manager=self.manager)
        self.assertStatus(state, LIFECYCLE_PENDING_APPROVAL)


# --------------------------------------------------------------------
# Registered / verified
# --------------------------------------------------------------------
class RegisteredAndVerifiedTests(Setup):
    def test_successful_registration_is_registered(self):
        approval_request, plan, registration_request, result = self.registered()
        state = self.derive(registration_result=result, approval_manager=self.manager)
        self.assertStatus(state, LIFECYCLE_REGISTERED)
        self.assertEqual(state["registration_result"]["status"], REGISTRATION_RESULT_REGISTERED)
        self.assertEqual(state["registration_request_id"], registration_request["request_id"])
        self.assertEqual(state["approval_request_id"], approval_request["request_id"])
        self.assertEqual(state["source_version"], plan["source_version"])
        self.assertIsNone(state["verification_result"])

    def test_already_registered_replay_is_registered(self):
        _, _, registration_request, result = self.registered()
        replay = register_approved_capability(
            registration_request["request_id"], self.manager, self.capability_system)
        self.assertEqual(replay["status"], REGISTRATION_RESULT_ALREADY_REGISTERED)
        self.assertStatus(self.derive(registration_result=replay), LIFECYCLE_REGISTERED)

    def test_verifier_verified_is_verified(self):
        approval_request, _, registration_request, result, verification = self.verified()
        state = self.derive(
            registration_result=result, verification_result=verification,
            approval_manager=self.manager)
        self.assertStatus(state, LIFECYCLE_VERIFIED)
        self.assertEqual(state["errors"], [])
        self.assertEqual(state["verification_result"]["status"], VERIFICATION_STATUS_VERIFIED)
        self.assertEqual(state["registration_request_id"], registration_request["request_id"])
        self.assertEqual(state["approval_request_id"], approval_request["request_id"])
        self.assertIsNotNone(state["registration_plan"])

    def test_full_chain_of_results_is_verified(self):
        approval_request, plan, registration_request, result, verification = self.verified()
        state = self.derive(
            build_result=self.build_result(), apply_request=self.apply_request(),
            test_evaluation=self.passing_evaluation(),
            human_approval_request=approval_request, approval_manager=self.manager,
            registration_plan=plan, registration_request_id=registration_request["request_id"],
            registration_result=result, verification_result=verification)
        self.assertStatus(state, LIFECYCLE_VERIFIED)

    def test_state_has_exactly_the_documented_keys(self):
        _, _, _, result, verification = self.verified()
        state = self.derive(registration_result=result, verification_result=verification)
        self.assertEqual(set(state.keys()), STATE_KEYS)
        self.assertEqual(set(self.derive().keys()), STATE_KEYS)


# --------------------------------------------------------------------
# Rejected / blocked / failed / rolled back
# --------------------------------------------------------------------
class RejectedTests(Setup):
    def test_rejected_capability_approval_is_rejected(self):
        request = self.registered_request()
        self.manager.reject(request["request_id"])
        state = self.derive(human_approval_request=request, approval_manager=self.manager)
        self.assertStatus(state, LIFECYCLE_REJECTED)
        self.assertTrue(state["errors"])

    def test_rejected_approval_can_never_become_approved(self):
        request = self.registered_request()
        self.manager.reject(request["request_id"])
        self.manager.approve(request["request_id"])  # ApprovalManager refuses
        state = self.derive(human_approval_request=request, approval_manager=self.manager)
        self.assertStatus(state, LIFECYCLE_REJECTED)

    def test_rejected_registration_approval_is_rejected(self):
        approval_request, plan, registration_request = self.chain()
        self.manager.reject(registration_request["request_id"])
        state = self.derive(
            human_approval_request=approval_request, registration_plan=plan,
            registration_request_id=registration_request["request_id"],
            approval_manager=self.manager)
        self.assertStatus(state, LIFECYCLE_REJECTED)

    def test_rejection_is_not_masked_by_a_later_registration_result(self):
        # One coherent chain: registered, but the stored registration
        # decision is later found REJECTED (the same drift the
        # verifier tests simulate). The later REGISTERED result must
        # not hide it.
        _, _, registration_request, result = self.registered()
        key = f"capability_approval:{registration_request['request_id']}"
        self.memory.set_state(key, dict(self.memory.get_state(key), status="REJECTED"))
        state = self.derive(registration_result=result, approval_manager=self.manager)
        self.assertStatus(state, LIFECYCLE_REJECTED)
        self.assertNotEqual(state["current_status"], LIFECYCLE_REGISTERED)


class BlockedTests(Setup):
    def test_blocked_human_approval_request_is_blocked_and_cannot_be_approved(self):
        request = self.blocked_human_request()
        self.manager.approve(request["request_id"])  # never stored -> nothing to approve
        state = self.derive(human_approval_request=request, approval_manager=self.manager)
        self.assertStatus(state, LIFECYCLE_BLOCKED)
        self.assertNotEqual(state["current_status"], LIFECYCLE_APPROVED)

    def test_blocked_registration_plan_is_blocked(self):
        state = self.derive(registration_plan=self.blocked_plan())
        self.assertStatus(state, LIFECYCLE_BLOCKED)

    def test_registration_blocked_by_undecided_approval_is_blocked(self):
        _, _, registration_request = self.chain()
        result = register_approved_capability(
            registration_request["request_id"], self.manager, self.capability_system)
        self.assertEqual(result["status"], REGISTRATION_RESULT_BLOCKED)
        state = self.derive(registration_result=result)
        self.assertStatus(state, LIFECYCLE_BLOCKED)
        self.assertNotEqual(state["current_status"], LIFECYCLE_REGISTERED)

    def test_blocked_build_result_is_blocked(self):
        state = self.derive(build_result=dict(self.build_result(), status="BLOCKED"))
        self.assertStatus(state, LIFECYCLE_BLOCKED)


class FailedTests(Setup):
    def test_failing_tests_are_failed(self):
        state = self.derive(build_result=self.build_result(),
                            test_evaluation=self.failing_evaluation())
        self.assertStatus(state, LIFECYCLE_FAILED)
        self.assertTrue(state["errors"])

    def test_failed_registration_is_failed(self):
        _, _, registration_request = self.chain()
        self.manager.approve(registration_request["request_id"])
        self.capability_system.register(NAME, "A different, pre-existing capability.")
        result = register_approved_capability(
            registration_request["request_id"], self.manager, self.capability_system)
        self.assertEqual(result["status"], REGISTRATION_RESULT_FAILED)
        state = self.derive(registration_result=result)
        self.assertStatus(state, LIFECYCLE_FAILED)

    def test_registered_but_failed_verification_is_failed(self):
        _, _, _, result = self.registered()
        self.memory._run("UPDATE capabilities SET description = ? WHERE name = ?",
                         ("A hand-edited description.", NAME))
        verification = verify_registered_capability(
            result, self.manager, self.capability_system)
        self.assertEqual(verification["status"], VERIFICATION_STATUS_FAILED)

        state = self.derive(registration_result=result, verification_result=verification,
                            approval_manager=self.manager)
        self.assertStatus(state, LIFECYCLE_FAILED)
        self.assertNotIn(state["current_status"], (LIFECYCLE_REGISTERED, LIFECYCLE_VERIFIED))
        self.assertTrue(any("description" in e for e in state["errors"]))

    def test_failed_verification_is_not_silently_corrected(self):
        _, _, _, result = self.registered()
        self.memory._run("UPDATE capabilities SET description = ? WHERE name = ?",
                         ("A hand-edited description.", NAME))
        verification = verify_registered_capability(
            result, self.manager, self.capability_system)
        rows_before = self.capability_system.all()
        first = self.derive(registration_result=result, verification_result=verification)
        second = self.derive(registration_result=result, verification_result=verification)
        self.assertStatus(first, LIFECYCLE_FAILED)
        self.assertEqual(first, second)
        self.assertEqual(self.capability_system.all(), rows_before)

    def test_unregistered_verification_is_failed(self):
        _, _, _, result = self.registered()
        self.memory._run("DELETE FROM capabilities WHERE name = ?", (NAME,))
        verification = verify_registered_capability(
            result, self.manager, self.capability_system)
        state = self.derive(registration_result=result, verification_result=verification)
        self.assertStatus(state, LIFECYCLE_FAILED)

    def test_later_positive_results_never_mask_an_earlier_failure(self):
        approval_request, plan, registration_request, result, verification = self.verified()
        state = self.derive(
            test_evaluation=self.failing_evaluation(),
            registration_result=result, verification_result=verification)
        self.assertStatus(state, LIFECYCLE_FAILED)


class RolledBackTests(Setup):
    def rollback(self, test_status="FAILED"):
        request = self.unstored_human_request()
        return build_code_change_rollback_decision(
            test_status, self.path, request["version"], self.versions)

    def test_completed_rollback_is_rolled_back(self):
        rollback = self.rollback()
        self.assertEqual(rollback["change_status"], "ROLLED_BACK")
        state = self.derive(test_evaluation=self.failing_evaluation(),
                            rollback_result=rollback)
        self.assertStatus(state, LIFECYCLE_ROLLED_BACK)

    def test_rolled_back_is_distinguishable_from_failed(self):
        failed = self.derive(test_evaluation=self.failing_evaluation())
        rolled_back = self.derive(test_evaluation=self.failing_evaluation(),
                                  rollback_result=self.rollback())
        self.assertStatus(failed, LIFECYCLE_FAILED)
        self.assertStatus(rolled_back, LIFECYCLE_ROLLED_BACK)
        self.assertNotEqual(failed["current_status"], rolled_back["current_status"])

    def test_rollback_wins_over_earlier_positive_results(self):
        _, _, _, result, verification = self.verified()
        state = self.derive(registration_result=result, verification_result=verification,
                            rollback_result=self.rollback())
        self.assertStatus(state, LIFECYCLE_ROLLED_BACK)

    def test_rollback_that_did_not_complete_is_failed_not_rolled_back(self):
        rollback = build_code_change_rollback_decision("FAILED", self.path, None, None)
        self.assertEqual(rollback["change_status"], "ROLLBACK_FAILED")
        state = self.derive(rollback_result=rollback)
        self.assertStatus(state, LIFECYCLE_FAILED)

    def test_kept_change_adds_nothing(self):
        kept = build_code_change_rollback_decision("PASSED", self.path, None, None)
        self.assertEqual(kept["change_status"], "KEPT")
        state = self.derive(build_result=self.build_result(), rollback_result=kept)
        self.assertStatus(state, LIFECYCLE_BUILT)


# --------------------------------------------------------------------
# Missing results can never produce REGISTERED / VERIFIED
# --------------------------------------------------------------------
class MissingResultTests(Setup):
    def test_missing_registration_result_cannot_produce_registered(self):
        approval_request, plan, registration_request = self.chain()
        self.manager.approve(registration_request["request_id"])
        state = self.derive(
            human_approval_request=approval_request, registration_plan=plan,
            registration_request_id=registration_request["request_id"],
            approval_manager=self.manager)
        self.assertStatus(state, LIFECYCLE_READY_FOR_REGISTRATION)
        self.assertIsNone(state["registration_result"])
        self.assertNotEqual(state["current_status"], LIFECYCLE_REGISTERED)

    def test_verified_verification_without_registration_result_is_invalid(self):
        _, _, _, _, verification = self.verified()
        state = self.derive(verification_result=verification)
        self.assertStatus(state, LIFECYCLE_INVALID)
        self.assertNotIn(state["current_status"], (LIFECYCLE_REGISTERED, LIFECYCLE_VERIFIED))

    def test_verification_of_a_failed_registration_cannot_be_verified(self):
        _, _, _, result, verification = self.verified()
        failed_registration = dict(result, status=REGISTRATION_RESULT_FAILED)
        state = self.derive(registration_result=failed_registration,
                            verification_result=verification)
        self.assertNotIn(state["current_status"], (LIFECYCLE_REGISTERED, LIFECYCLE_VERIFIED))

    def test_verification_of_a_different_registration_is_invalid(self):
        _, _, _, result, verification = self.verified()
        other = dict(verification, request_id="registration-approval-someone-else")
        state = self.derive(registration_result=result, verification_result=other)
        self.assertStatus(state, LIFECYCLE_INVALID)

    def test_missing_verification_result_cannot_produce_verified(self):
        _, _, _, result = self.registered()
        state = self.derive(registration_result=result, approval_manager=self.manager)
        self.assertStatus(state, LIFECYCLE_REGISTERED)
        self.assertIsNone(state["verification_result"])
        self.assertNotEqual(state["current_status"], LIFECYCLE_VERIFIED)

    def test_a_verified_result_reporting_mismatches_is_not_verified(self):
        _, _, _, result, verification = self.verified()
        contradictory = dict(verification, mismatches=["something drifted"])
        state = self.derive(registration_result=result, verification_result=contradictory)
        self.assertStatus(state, LIFECYCLE_INVALID)


# --------------------------------------------------------------------
# VERIFIED is not ACTIVE
# --------------------------------------------------------------------
class VerifiedIsNotActiveTests(Setup):
    def test_there_is_no_active_lifecycle_status(self):
        self.assertNotIn("ACTIVE", ALL_LIFECYCLE_STATUSES)
        self.assertFalse([n for n in dir(lifecycle_module) if n.endswith("ACTIVE")])

    def test_verified_capability_is_not_active(self):
        _, _, _, result, verification = self.verified()
        state = self.derive(registration_result=result, verification_result=verification,
                            approval_manager=self.manager)
        self.assertStatus(state, LIFECYCLE_VERIFIED)
        self.assertNotEqual(state["current_status"], "ACTIVE")
        self.assertIn("does not mean the capability is active", state["reason"])
        row = next(c for c in self.capability_system.all() if c["name"] == NAME)
        self.assertFalse(row["enabled"])
        self.assertNotEqual(row["status"], "active")

    def test_deriving_the_state_never_enables_the_capability(self):
        _, _, _, result, verification = self.verified()
        rows_before = self.capability_system.all()
        self.derive(registration_result=result, verification_result=verification,
                    approval_manager=self.manager)
        self.assertEqual(self.capability_system.all(), rows_before)


# --------------------------------------------------------------------
# Consistency / determinism
# --------------------------------------------------------------------
class ConsistencyTests(Setup):
    def test_result_for_a_different_capability_is_invalid(self):
        state = build_capability_lifecycle_state(
            "some_other_capability", build_result=self.build_result())
        self.assertStatus(state, LIFECYCLE_INVALID)
        self.assertTrue(any(NAME in e for e in state["errors"]))

    def test_disagreeing_approval_ids_are_invalid(self):
        approval_request, plan, _ = self.chain()
        state = self.derive(human_approval_request=self.unstored_human_request(),
                            registration_plan=plan)
        self.assertStatus(state, LIFECYCLE_INVALID)

    def test_no_evidence_is_invalid(self):
        state = self.derive()
        self.assertStatus(state, LIFECYCLE_INVALID)
        self.assertTrue(state["errors"])

    def test_blank_capability_name_is_invalid(self):
        for bad in (None, "", "   ", 42):
            state = build_capability_lifecycle_state(bad, build_result=self.build_result())
            self.assertStatus(state, LIFECYCLE_INVALID)

    def test_malformed_results_are_invalid_and_never_raise(self):
        for field in ("build_result", "apply_request", "test_evaluation",
                      "human_approval_request", "registration_plan",
                      "registration_result", "verification_result", "rollback_result"):
            state = self.derive(**{field: "not a dict"})
            self.assertStatus(state, LIFECYCLE_INVALID)

    def test_approval_id_without_a_manager_is_invalid(self):
        state = self.derive(approval_request_id="approval-x")
        self.assertStatus(state, LIFECYCLE_INVALID)

    def test_unknown_explicit_approval_id_is_invalid(self):
        state = self.derive(approval_request_id="does-not-exist",
                            approval_manager=self.manager)
        self.assertStatus(state, LIFECYCLE_INVALID)

    def test_the_same_results_always_give_the_same_state(self):
        _, _, _, result, verification = self.verified()
        args = dict(registration_result=result, verification_result=verification,
                    approval_manager=self.manager)
        self.assertEqual(self.derive(**args), self.derive(**args))


# --------------------------------------------------------------------
# State tracking never executes, activates, decides, or modifies anything
# --------------------------------------------------------------------
class NoSideEffectTests(Setup):
    def full_arguments(self):
        approval_request, plan, registration_request, result, verification = self.verified()
        return dict(
            build_result=self.build_result(), apply_request=self.apply_request(),
            test_evaluation=self.passing_evaluation(),
            human_approval_request=approval_request, approval_manager=self.manager,
            registration_plan=plan, registration_request_id=registration_request["request_id"],
            registration_result=result, verification_result=verification)

    def test_deriving_a_state_never_executes_a_capability(self):
        arguments = self.full_arguments()
        with mock.patch.object(Capability, "execute",
                               side_effect=AssertionError("capability executed")) as spy:
            state = self.derive(**arguments)
        spy.assert_not_called()
        self.assertStatus(state, LIFECYCLE_VERIFIED)

    def test_deriving_a_state_does_not_touch_handlers_or_registry(self):
        arguments = self.full_arguments()
        handlers_before = list(self.handlers.list_registered())
        rows_before = self.capability_system.all()
        self.derive(**arguments)
        self.assertEqual(list(self.handlers.list_registered()), handlers_before)
        self.assertEqual(self.capability_system.all(), rows_before)

    def test_deriving_a_state_only_reads_the_approval_manager(self):
        arguments = self.full_arguments()
        self.manager.calls.clear()
        request_id = arguments["registration_request_id"]
        before = self.manager.get_stored_record(request_id)
        self.manager.calls.clear()
        self.derive(**arguments)
        self.assertTrue(self.manager.calls)
        self.assertEqual(set(self.manager.calls), {"get_stored_record"})
        self.assertEqual(self.manager.get_stored_record(request_id), before)

    def test_deriving_a_state_does_not_create_versions(self):
        arguments = self.full_arguments()
        versions_before = self.versions.history()
        self.derive(**arguments)
        self.assertEqual(self.versions.history(), versions_before)

    def test_inputs_are_not_mutated(self):
        arguments = self.full_arguments()
        snapshot = {k: copy.deepcopy(v) for k, v in arguments.items()
                    if k != "approval_manager"}
        self.derive(**arguments)
        for key, value in snapshot.items():
            self.assertEqual(arguments[key], value, key)

    def test_module_never_calls_activation_execution_or_decision_apis(self):
        with open(lifecycle_module.__file__, encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        forbidden_attrs = {
            "set_enabled", "register", "register_capability", "replace",
            "replace_capability", "unregister", "create_version", "rollback_to",
            "create_request", "approve", "reject", "execute", "run", "set_state",
            "write", "write_text", "system", "popen",
        }
        forbidden_names = {"exec", "eval", "open", "compile", "__import__"}
        forbidden_imports = {"subprocess", "shutil", "importlib", "sqlite3"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute):
                    self.assertNotIn(func.attr, forbidden_attrs, func.attr)
                elif isinstance(func, ast.Name):
                    self.assertNotIn(func.id, forbidden_names, func.id)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn(alias.name.split(".")[0], forbidden_imports)
            elif isinstance(node, ast.ImportFrom):
                self.assertNotIn((node.module or "").split(".")[0], forbidden_imports)


if __name__ == "__main__":
    unittest.main()
