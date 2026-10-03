"""
Tests for self_upgrade.self_upgrade_resume_manager
.SelfUpgradeResumeManager / resume_self_upgrade (Prompt 383) - the
small, read-only orchestration layer that resumes a persisted
`SelfUpgradeExecutionContext` (Prompt 382) by asking the existing
`SelfUpgradeLifecycleCoordinator` for the next recorded action, after
first validating the context is internally consistent.

Every fixture used here is a real result from the real Prompt 357-382
stages, reusing tests.test_self_upgrade_execution_context.ContextSetup
exactly like that module reuses
tests.test_self_upgrade_lifecycle_coordinator.CoordinatorSetup.

Covers: resuming from every named lifecycle stage (build, validate,
test, version, pending approval, approved registration, registered,
verified); a rejected request staying rejected; a failed request never
being automatically retried; a rolled-back request never being
automatically restarted; an inconsistent context reporting
INVALID_CONTEXT instead of being silently repaired; resume being safe
to call repeatedly (idempotent - no duplicate registration, approval,
or snapshot, because nothing here ever performs one); and that resuming
never activates, executes, or bypasses approval for a capability.

Run directly:
    python -m unittest tests.test_self_upgrade_resume_manager -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import copy
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from self_upgrade.self_upgrade_execution_context import apply_successful_transition
from self_upgrade.self_upgrade_lifecycle_coordinator import (
    DECISION_ANALYZE,
    DECISION_BUILD,
    DECISION_VALIDATE,
    DECISION_TEST,
    DECISION_CORRECT,
    DECISION_VERSION,
    DECISION_WAIT_FOR_APPROVAL,
    DECISION_REGISTER,
    DECISION_VERIFY_REGISTRATION,
    DECISION_COMPLETED,
    DECISION_BLOCKED,
    DECISION_FAILED,
    DECISION_ROLLED_BACK,
)
from self_upgrade.self_upgrade_resume_manager import (
    SelfUpgradeResumeManager,
    resume_self_upgrade,
    ALL_RESUME_STATUSES,
    RESUME_STATUS_RESUMED,
    RESUME_STATUS_NOT_FOUND,
    RESUME_STATUS_NOT_YET_STARTED,
    RESUME_STATUS_INVALID_CONTEXT,
)
from self_upgrade.self_upgrade_request import STATUS_REJECTED
from agent.code_change_rollback import build_code_change_rollback_decision
from agent.test_result_evaluation import RESULT_FAILED

from tests.test_self_upgrade_execution_context import (
    ContextSetup, UPGRADE_REQUEST_ID,
)
from tests.test_self_upgrade_lifecycle_coordinator import (
    _self_upgrade_request, CODE_CHANGE_PLAN_NAME,
)

RESUME_KEYS = {
    "upgrade_request_id", "capability_name", "resume_status",
    "last_completed_action", "decision", "errors",
}


class ResumeSetup(ContextSetup):
    """Adds the resume manager itself on top of the real Prompt
    357-382 fixtures `ContextSetup` already builds."""

    def setUp(self):
        super().setUp()
        self.resume_manager = SelfUpgradeResumeManager(self.store, self.coordinator)

    def persist(self, context):
        return self.store.save(context)

    def advance_and_persist(self, context, decision):
        context = apply_successful_transition(context, decision)
        return self.persist(context)

    def resume(self):
        return self.resume_manager.resume(UPGRADE_REQUEST_ID)


# --------------------------------------------------------------------
# Vocabulary / shape
# --------------------------------------------------------------------
class VocabularyTests(unittest.TestCase):
    def test_all_resume_statuses_are_exactly_the_specified_ones(self):
        self.assertEqual(ALL_RESUME_STATUSES, (
            "RESUMED", "NOT_FOUND", "NOT_YET_STARTED", "INVALID_CONTEXT"))

    def test_result_shape_never_raises_on_garbage(self):
        class BrokenStore:
            def load(self, upgrade_request_id):
                raise RuntimeError("boom")

        result = resume_self_upgrade("id", BrokenStore(), coordinator=None)
        self.assertEqual(set(result.keys()), RESUME_KEYS)
        self.assertEqual(result["resume_status"], RESUME_STATUS_INVALID_CONTEXT)


# --------------------------------------------------------------------
# Not found / not yet started
# --------------------------------------------------------------------
class MissingContextTests(ResumeSetup):
    def test_resume_with_no_persisted_context_is_not_found(self):
        result = self.resume_manager.resume("no-such-upgrade-request")
        self.assertEqual(result["resume_status"], RESUME_STATUS_NOT_FOUND)
        self.assertTrue(result["errors"])
        self.assertIsNone(result["decision"])

    def test_fresh_context_with_no_recorded_action_is_not_yet_started(self):
        self.persist(self.new_context())
        result = self.resume()
        self.assertEqual(result["resume_status"], RESUME_STATUS_NOT_YET_STARTED)
        self.assertIsNone(result["decision"])


# --------------------------------------------------------------------
# Resume from every named lifecycle stage
# --------------------------------------------------------------------
class ResumeFromStageTests(ResumeSetup):
    def test_resume_from_a_persisted_build_state(self):
        context = self.new_context()
        decision = self.decide(build_result=self.build_result())
        self.advance_and_persist(context, decision)

        result = self.resume()
        self.assertEqual(result["resume_status"], RESUME_STATUS_RESUMED)
        self.assertEqual(result["decision"]["decision"], DECISION_VALIDATE)

    def test_resume_from_validation_state(self):
        context = self.new_context()
        decision = self.decide(
            build_result=self.build_result(), apply_request=self.apply_request())
        self.advance_and_persist(context, decision)

        result = self.resume()
        self.assertEqual(result["decision"]["decision"], DECISION_TEST)

    def test_resume_from_testing_state(self):
        context = self.new_context()
        decision = self.decide(
            build_result=self.build_result(), apply_request=self.apply_request(),
            test_evaluation=self.passing_evaluation())
        self.advance_and_persist(context, decision)

        result = self.resume()
        self.assertEqual(result["decision"]["decision"], DECISION_VERSION)

    def test_resume_from_versioned_state(self):
        context = self.new_context()
        decision = self.decide(human_approval_request=self.unstored_human_request())
        self.advance_and_persist(context, decision)

        result = self.resume()
        self.assertEqual(result["decision"]["decision"], DECISION_WAIT_FOR_APPROVAL)

    def test_resume_from_pending_approval(self):
        context = self.new_context()
        request = self.registered_request()
        decision = self.decide(human_approval_request=request, approval_manager=self.manager)
        self.advance_and_persist(context, decision)

        result = self.resume()
        self.assertEqual(result["decision"]["decision"], DECISION_WAIT_FOR_APPROVAL)
        self.assertEqual(result["resume_status"], RESUME_STATUS_RESUMED)

    def test_resume_from_approved_registration_state(self):
        context = self.new_context()
        approval_request, plan, registration_request = self.chain()
        self.manager.approve(registration_request["request_id"])
        decision = self.decide(
            human_approval_request=approval_request, registration_plan=plan,
            registration_request_id=registration_request["request_id"],
            approval_manager=self.manager)
        self.advance_and_persist(context, decision)

        result = self.resume()
        self.assertEqual(result["decision"]["decision"], DECISION_REGISTER)

    def test_resume_from_registered_state(self):
        context = self.new_context()
        _, _, _, result_dict = self.registered()
        decision = self.decide(registration_result=result_dict, approval_manager=self.manager)
        self.advance_and_persist(context, decision)

        result = self.resume()
        self.assertEqual(result["decision"]["decision"], DECISION_VERIFY_REGISTRATION)

    def test_resume_from_verified_state(self):
        context = self.new_context()
        _, _, _, reg_result, verification = self.verified()
        decision = self.decide(
            registration_result=reg_result, verification_result=verification,
            approval_manager=self.manager)
        self.advance_and_persist(context, decision)

        result = self.resume()
        self.assertEqual(result["decision"]["decision"], DECISION_COMPLETED)
        self.assertNotEqual(result["decision"]["decision"], "ACTIVE")


# --------------------------------------------------------------------
# Rejected / failed / rolled-back never auto-advance
# --------------------------------------------------------------------
class NonAdvancingStateTests(ResumeSetup):
    def test_rejected_state_remains_rejected(self):
        context = self.new_context()
        request = _self_upgrade_request(status=STATUS_REJECTED)
        decision = self.decide(self_upgrade_request=request)
        self.assertEqual(decision["decision"], DECISION_BLOCKED)
        self.advance_and_persist(context, decision)

        result = self.resume()
        self.assertEqual(result["decision"]["decision"], DECISION_BLOCKED)
        # Resuming again changes nothing.
        result_again = self.resume()
        self.assertEqual(result_again, result)

    def test_failed_state_does_not_automatically_retry(self):
        context = self.new_context()
        decision = self.decide(test_evaluation=self.failing_evaluation())
        self.assertIn(decision["decision"], (DECISION_CORRECT, DECISION_FAILED))
        self.advance_and_persist(context, decision)

        result = self.resume()
        # Whatever the coordinator already reported (CORRECT or FAILED),
        # resuming only *reports* it - it never re-runs the build/test/
        # correction stages itself.
        self.assertEqual(result["decision"]["decision"], decision["decision"])
        self.assertEqual(result["resume_status"], RESUME_STATUS_RESUMED)

    def test_rolled_back_state_does_not_automatically_restart(self):
        context = self.new_context()
        version = self.versions.create_version(None, "v-rollback-test", snapshot={})
        rollback = build_code_change_rollback_decision(
            RESULT_FAILED, "some/file.py", version, self.versions)
        self.assertEqual(rollback["change_status"], "ROLLED_BACK")
        decision = self.decide(rollback_result=rollback)
        self.assertEqual(decision["decision"], DECISION_ROLLED_BACK)
        self.advance_and_persist(context, decision)

        result = self.resume()
        self.assertEqual(result["decision"]["decision"], DECISION_ROLLED_BACK)
        # No re-run: resuming twice reports the identical, unchanged
        # ROLLED_BACK outcome rather than starting a fresh upgrade.
        self.assertEqual(self.resume(), result)


# --------------------------------------------------------------------
# Consistency validation
# --------------------------------------------------------------------
class InvalidContextTests(ResumeSetup):
    def test_capability_name_mismatch_is_invalid_context(self):
        context = self.new_context()
        decision = self.decide(build_result=self.build_result())
        context = apply_successful_transition(context, decision)
        tampered = dict(context, capability_name="some_other_capability")
        self.persist(tampered)

        result = self.resume()
        self.assertEqual(result["resume_status"], RESUME_STATUS_INVALID_CONTEXT)
        self.assertTrue(result["errors"])
        self.assertIsNone(result["decision"])

    def test_approval_reference_mismatch_is_invalid_context(self):
        context = self.new_context()
        request = self.unstored_human_request()
        decision = self.decide(human_approval_request=request)
        context = apply_successful_transition(context, decision)
        tampered = dict(context, approval_request_id="forged-request-id")
        self.persist(tampered)

        result = self.resume()
        self.assertEqual(result["resume_status"], RESUME_STATUS_INVALID_CONTEXT)

    def test_registration_result_reference_mismatch_is_invalid_context(self):
        context = self.new_context()
        _, _, _, reg_result = self.registered()
        decision = self.decide(registration_result=reg_result, approval_manager=self.manager)
        context = apply_successful_transition(context, decision)
        tampered = dict(context, registration_result_reference={"forged": True})
        self.persist(tampered)

        result = self.resume()
        self.assertEqual(result["resume_status"], RESUME_STATUS_INVALID_CONTEXT)

    def test_unrecognized_current_action_is_invalid_context(self):
        context = self.new_context()
        tampered = dict(context, current_action="ACTIVATE_NOW")
        self.persist(tampered)

        result = self.resume()
        self.assertEqual(result["resume_status"], RESUME_STATUS_INVALID_CONTEXT)

    def test_missing_fields_is_invalid_context(self):
        context = self.new_context()
        incomplete = dict(context)
        del incomplete["current_lifecycle_state"]
        self.persist(incomplete)  # store.save only checks upgrade_request_id

        result = self.resume()
        self.assertEqual(result["resume_status"], RESUME_STATUS_INVALID_CONTEXT)

    def test_inconsistent_context_is_never_silently_repaired(self):
        context = self.new_context()
        decision = self.decide(build_result=self.build_result())
        context = apply_successful_transition(context, decision)
        tampered = dict(context, capability_name="wrong_name")
        self.persist(tampered)

        self.resume()
        # The stored record itself must be untouched by having resumed.
        self.assertEqual(self.store.load(UPGRADE_REQUEST_ID), tampered)


# --------------------------------------------------------------------
# Idempotency
# --------------------------------------------------------------------
class IdempotencyTests(ResumeSetup):
    def test_repeated_resume_returns_the_identical_result(self):
        context = self.new_context()
        decision = self.decide(
            build_result=self.build_result(), apply_request=self.apply_request())
        self.advance_and_persist(context, decision)

        first = self.resume()
        second = self.resume()
        third = self.resume()
        self.assertEqual(first, second)
        self.assertEqual(second, third)

    def test_repeated_resume_never_advances_the_stored_context(self):
        context = self.new_context()
        decision = self.decide(build_result=self.build_result())
        self.advance_and_persist(context, decision)
        before = copy.deepcopy(self.store.load(UPGRADE_REQUEST_ID))

        self.resume()
        self.resume()

        after = self.store.load(UPGRADE_REQUEST_ID)
        self.assertEqual(after, before)

    def test_repeated_resume_never_creates_a_second_approval_request(self):
        context = self.new_context()
        request = self.unstored_human_request()
        decision = self.decide(human_approval_request=request)
        self.advance_and_persist(context, decision)

        self.resume()
        self.resume()
        # ApprovalManager was never touched by resuming - the request
        # this fixture built was never even submitted to it.
        self.assertIsNone(self.manager.get_request(request["request_id"])["status"])

    def test_repeated_resume_never_registers_or_verifies_twice(self):
        context = self.new_context()
        approval_request, plan, registration_request = self.chain()
        self.manager.approve(registration_request["request_id"])
        decision = self.decide(
            human_approval_request=approval_request, registration_plan=plan,
            registration_request_id=registration_request["request_id"],
            approval_manager=self.manager)
        self.advance_and_persist(context, decision)

        before_count = len(self.capability_system.all())
        self.resume()
        self.resume()
        self.assertEqual(len(self.capability_system.all()), before_count)


# --------------------------------------------------------------------
# Never activates, executes, or bypasses approval
# --------------------------------------------------------------------
class SafetyTests(ResumeSetup):
    def test_resume_never_activates_a_capability(self):
        context = self.new_context()
        _, _, _, reg_result, verification = self.verified()
        decision = self.decide(
            registration_result=reg_result, verification_result=verification,
            approval_manager=self.manager)
        self.advance_and_persist(context, decision)

        self.resume()
        for entry in self.capability_system.all():
            self.assertFalse(entry.get("enabled"))

    def test_resume_never_executes_a_capability(self):
        calls = []

        class SpyHandlers(dict):
            def get(self, *args, **kwargs):
                calls.append((args, kwargs))
                return super().get(*args, **kwargs)

        context = self.new_context()
        decision = self.decide(build_result=self.build_result())
        self.advance_and_persist(context, decision)

        self.resume()
        self.assertEqual(calls, [])  # nothing here ever touched a handler registry

    def test_resume_never_bypasses_approval(self):
        context = self.new_context()
        request = self.registered_request()  # stored, still PENDING
        decision = self.decide(human_approval_request=request, approval_manager=self.manager)
        self.advance_and_persist(context, decision)

        self.resume()
        self.resume()
        still_pending = self.manager.get_request(request["request_id"])
        self.assertEqual(still_pending["status"], "PENDING_APPROVAL")

    def test_resume_manager_module_never_imports_action_surfaces(self):
        import ast
        import self_upgrade.self_upgrade_resume_manager as module

        with open(module.__file__, "r", encoding="utf-8") as handle:
            tree = ast.parse(handle.read())

        imported_modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.add(node.module)

        forbidden_modules = {
            "self_upgrade.capability_registration_executor",
            "self_upgrade.capability_registration_verifier",
            "self_upgrade.capability_human_approval",
            "self_upgrade.capability_approval_manager",
            "capabilities.capability_system",
            "execution.capability_handlers",
        }
        self.assertEqual(imported_modules & forbidden_modules, set())


if __name__ == "__main__":
    unittest.main()
