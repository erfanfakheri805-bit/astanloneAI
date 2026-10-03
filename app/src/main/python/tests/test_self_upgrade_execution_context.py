"""
Tests for self_upgrade.self_upgrade_execution_context
.SelfUpgradeExecutionContext / SelfUpgradeExecutionContextStore, and the
small `SelfUpgradeLifecycleCoordinator.advance`/`.resume` integration
added alongside it (Prompt 382) - a small persistent record of where a
single self-upgrade request currently stands across the controlled,
multi-step Self-Upgrade lifecycle, so the coordinator can be asked
"what's next?" again after a restart without restarting stages that
already completed.

Every fixture used here is a real result from the real Prompt 357-381
stages, reusing tests.test_self_upgrade_lifecycle_coordinator
.CoordinatorSetup exactly like that module reuses
tests.test_capability_lifecycle.Setup.

Covers: creating a new context; saving and loading a context; a
successful transition updating the context; a failed transition
preserving the previous successful state; the approval request id,
version/snapshot reference, registration result, and verification
result all being preserved across transitions; the coordinator resuming
from an existing context without restarting completed stages;
VERIFIED never becoming ACTIVE; that persistence never executes or
activates a capability; and that every existing test in this project
keeps passing untouched.

Run directly:
    python -m unittest tests.test_self_upgrade_execution_context -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from memory.memory_system import MemorySystem
from self_upgrade.self_upgrade_lifecycle_coordinator import (
    SelfUpgradeLifecycleCoordinator,
    DECISION_ANALYZE,
    DECISION_BUILD,
    DECISION_VALIDATE,
    DECISION_TEST,
    DECISION_VERSION,
    DECISION_WAIT_FOR_APPROVAL,
    DECISION_REGISTER,
    DECISION_VERIFY_REGISTRATION,
    DECISION_COMPLETED,
    DECISION_BLOCKED,
    DECISION_INVALID,
    ALL_COORDINATOR_DECISIONS,
)
from self_upgrade.self_upgrade_execution_context import (
    CONTEXT_FIELDS,
    build_execution_context,
    apply_successful_transition,
    apply_failed_transition,
    SelfUpgradeExecutionContextStore,
)
from self_upgrade.capability_lifecycle import LIFECYCLE_VERIFIED
from self_upgrade.self_upgrade_request import STATUS_REQUESTED, STATUS_REJECTED

from tests.test_self_upgrade_lifecycle_coordinator import (
    CoordinatorSetup, _self_upgrade_request, _ready_creation_plan, CODE_CHANGE_PLAN_NAME,
)

UPGRADE_REQUEST_ID = "upgrade_request-382-1"

# No decision here is, or ever produces, an "ACTIVE"-sounding action.
assert "ACTIVE" not in ALL_COORDINATOR_DECISIONS


class ContextSetup(CoordinatorSetup):
    """Adds a real, temp-file-backed `MemorySystem`/store on top of the
    real Prompt 361-381 fixtures `CoordinatorSetup` already builds -
    this is the project's existing persistence mechanism (Prompt 382's
    own PERSISTENCE requirement), not a second one."""

    def setUp(self):
        super().setUp()
        self.store = SelfUpgradeExecutionContextStore(self.memory)

    def new_context(self, capability_name=CODE_CHANGE_PLAN_NAME):
        context = build_execution_context(UPGRADE_REQUEST_ID, capability_name=capability_name)
        self.assertIsNotNone(context)
        return context


# --------------------------------------------------------------------
# Creating a new execution context
# --------------------------------------------------------------------
class CreateContextTests(ContextSetup):
    def test_new_context_has_every_field_and_a_valid_initial_state(self):
        context = self.new_context()
        self.assertEqual(set(context.keys()), set(CONTEXT_FIELDS))
        self.assertEqual(context["upgrade_request_id"], UPGRADE_REQUEST_ID)
        self.assertEqual(context["capability_name"], CODE_CHANGE_PLAN_NAME)
        self.assertIsNone(context["current_action"])
        self.assertIsNone(context["current_lifecycle_state"])
        self.assertIsNone(context["last_completed_action"])
        self.assertIsNone(context["last_error"])
        for field in (
            "build_spec_reference", "implementation_spec_reference", "version_reference",
            "approval_request_id", "registration_plan_reference",
            "registration_result_reference", "verification_result_reference",
        ):
            self.assertIsNone(context[field])
        self.assertTrue(context["created_at"])
        self.assertTrue(context["updated_at"])

    def test_blank_upgrade_request_id_never_produces_a_context(self):
        self.assertIsNone(build_execution_context(None))
        self.assertIsNone(build_execution_context(""))
        self.assertIsNone(build_execution_context("   "))


# --------------------------------------------------------------------
# Saving and loading a context
# --------------------------------------------------------------------
class SaveAndLoadTests(ContextSetup):
    def test_save_then_load_round_trips(self):
        context = self.new_context()
        saved = self.store.save(context)
        self.assertEqual(saved, context)
        loaded = self.store.load(UPGRADE_REQUEST_ID)
        self.assertEqual(loaded, context)

    def test_load_unknown_id_returns_none(self):
        self.assertIsNone(self.store.load("no-such-upgrade-request"))

    def test_save_rejects_invalid_context(self):
        self.assertIsNone(self.store.save({"not": "a context"}))
        self.assertIsNone(self.store.save(None))

    def test_get_or_create_creates_once_then_reuses(self):
        first = self.store.get_or_create(UPGRADE_REQUEST_ID, capability_name=CODE_CHANGE_PLAN_NAME)
        self.assertIsNotNone(first)
        # Mutate the stored copy's action out-of-band, then confirm a
        # second get_or_create call loads that stored state back rather
        # than recreating (and clobbering) it.
        advanced = dict(first, current_action=DECISION_BUILD)
        self.store.save(advanced)
        second = self.store.get_or_create(UPGRADE_REQUEST_ID)
        self.assertEqual(second["current_action"], DECISION_BUILD)

    def test_context_survives_a_fresh_memory_system_pointed_at_the_same_file(self):
        """The project's own persistence guarantee: a context saved
        through one MemorySystem is readable through a second one
        opened against the same on-disk database file - i.e. it
        survives a normal application restart."""
        db_path = tempfile.mktemp(suffix=".db")
        memory_a = MemorySystem(db_path)
        store_a = SelfUpgradeExecutionContextStore(memory_a)
        context = build_execution_context(UPGRADE_REQUEST_ID, capability_name=CODE_CHANGE_PLAN_NAME)
        store_a.save(context)

        memory_b = MemorySystem(db_path)
        store_b = SelfUpgradeExecutionContextStore(memory_b)
        reloaded = store_b.load(UPGRADE_REQUEST_ID)
        self.assertEqual(reloaded, context)


# --------------------------------------------------------------------
# Successful transitions update the context
# --------------------------------------------------------------------
class SuccessfulTransitionTests(ContextSetup):
    def test_successful_transition_advances_action_and_lifecycle_state(self):
        context = self.new_context()
        decision = self.decide(build_result=self.build_result())
        self.assertEqual(decision["decision"], DECISION_VALIDATE)

        updated = apply_successful_transition(context, decision)
        self.assertEqual(updated["current_action"], DECISION_VALIDATE)
        self.assertEqual(updated["current_lifecycle_state"], decision["lifecycle_state"])
        # Nothing was "current" before this first real decision, so
        # nothing has completed yet.
        self.assertIsNone(updated["last_completed_action"])
        self.assertIsNone(updated["last_error"])
        self.assertNotEqual(updated, context)  # never mutated in place
        self.assertIsNone(context["current_action"])  # original untouched

    def test_last_completed_action_tracks_the_previous_current_action(self):
        context = self.new_context()
        decision_1 = self.decide(build_result=self.build_result())
        context = apply_successful_transition(context, decision_1)
        self.assertEqual(context["current_action"], DECISION_VALIDATE)

        decision_2 = self.decide(
            build_result=self.build_result(), apply_request=self.apply_request())
        context = apply_successful_transition(context, decision_2)
        self.assertEqual(context["last_completed_action"], DECISION_VALIDATE)
        self.assertEqual(context["current_action"], DECISION_TEST)

    def test_pre_pipeline_analyze_and_build_also_advance_the_context(self):
        context = self.new_context()
        request = _self_upgrade_request(status=STATUS_REQUESTED)
        decision = self.decide(self_upgrade_request=request)
        self.assertEqual(decision["decision"], DECISION_ANALYZE)
        context = apply_successful_transition(context, decision)
        self.assertEqual(context["current_action"], DECISION_ANALYZE)
        self.assertIsNone(context["current_lifecycle_state"])

        plan = _ready_creation_plan()
        decision = self.decide(creation_plan=plan)
        self.assertEqual(decision["decision"], DECISION_BUILD)
        context = apply_successful_transition(context, decision)
        self.assertEqual(context["current_action"], DECISION_BUILD)
        self.assertEqual(context["last_completed_action"], DECISION_ANALYZE)

    def test_blocked_decision_is_still_a_successful_transition(self):
        """A rejected/blocked approval is a real, valid lifecycle
        decision - it must be recorded, not silently dropped or left
        at whatever came before (context rule 4)."""
        context = self.new_context()
        request = _self_upgrade_request(status=STATUS_REJECTED)
        decision = self.decide(self_upgrade_request=request)
        self.assertEqual(decision["decision"], DECISION_BLOCKED)

        context = apply_successful_transition(context, decision)
        self.assertEqual(context["current_action"], DECISION_BLOCKED)
        self.assertIsNone(context["last_error"])


# --------------------------------------------------------------------
# Failed transitions preserve the previous successful state
# --------------------------------------------------------------------
class FailedTransitionTests(ContextSetup):
    def test_invalid_decision_preserves_previous_state_and_records_error(self):
        context = self.new_context()
        good_decision = self.decide(build_result=self.build_result())
        context = apply_successful_transition(context, good_decision)
        before = dict(context)

        bad_decision = self.decide(build_result="not a real build result")
        self.assertEqual(bad_decision["decision"], DECISION_INVALID)

        after = apply_successful_transition(context, bad_decision)
        self.assertEqual(after["current_action"], before["current_action"])
        self.assertEqual(after["current_lifecycle_state"], before["current_lifecycle_state"])
        self.assertEqual(after["last_completed_action"], before["last_completed_action"])
        self.assertTrue(after["last_error"])
        self.assertNotEqual(after["updated_at"], before["updated_at"])

    def test_explicit_error_preserves_previous_state(self):
        context = self.new_context()
        decision = self.decide(build_result=self.build_result())
        context = apply_successful_transition(context, decision)

        failed = apply_failed_transition(context, "Unexpected exception while validating.")
        self.assertEqual(failed["current_action"], context["current_action"])
        self.assertEqual(failed["current_lifecycle_state"], context["current_lifecycle_state"])
        self.assertEqual(failed["last_error"], "Unexpected exception while validating.")

    def test_failed_transition_on_a_fresh_context_stays_at_the_initial_state(self):
        context = self.new_context()
        failed = apply_failed_transition(context, "boom")
        self.assertIsNone(failed["current_action"])
        self.assertIsNone(failed["current_lifecycle_state"])
        self.assertEqual(failed["last_error"], "boom")

    def test_invalid_context_is_returned_unchanged(self):
        self.assertIsNone(apply_successful_transition(None, {"decision": DECISION_BUILD}))
        garbage = {"not": "a context"}
        self.assertEqual(apply_failed_transition(garbage, "boom"), garbage)


# --------------------------------------------------------------------
# References preserved across transitions
# --------------------------------------------------------------------
class ReferencePreservationTests(ContextSetup):
    def test_approval_request_id_is_preserved(self):
        context = self.new_context()
        request = self.unstored_human_request()
        decision = self.decide(human_approval_request=request)
        self.assertEqual(decision["decision"], DECISION_WAIT_FOR_APPROVAL)

        context = apply_successful_transition(context, decision)
        self.assertEqual(context["approval_request_id"], request["request_id"])

        # A later transition that doesn't itself carry a fresh approval
        # id must not erase the one already on record (context rule 5).
        next_decision = self.decide(
            build_result=self.build_result(), apply_request=self.apply_request())
        context = apply_successful_transition(context, next_decision)
        self.assertEqual(context["approval_request_id"], request["request_id"])

    def test_version_snapshot_reference_is_preserved(self):
        context = self.new_context()
        request = self.unstored_human_request()
        decision = self.decide(human_approval_request=request)
        context = apply_successful_transition(context, decision)
        self.assertEqual(context["version_reference"]["id"], request["version"]["id"])

    def test_registration_result_is_preserved(self):
        context = self.new_context()
        _, _, _, result = self.registered()
        decision = self.decide(registration_result=result)
        self.assertEqual(decision["decision"], DECISION_VERIFY_REGISTRATION)

        context = apply_successful_transition(context, decision)
        self.assertEqual(
            context["registration_result_reference"],
            decision["lifecycle_state"]["registration_result"])

    def test_verification_result_is_preserved(self):
        context = self.new_context()
        _, _, _, result, verification = self.verified()
        decision = self.decide(registration_result=result, verification_result=verification)
        self.assertEqual(decision["decision"], DECISION_COMPLETED)

        context = apply_successful_transition(context, decision)
        self.assertEqual(
            context["verification_result_reference"],
            decision["lifecycle_state"]["verification_result"])

    def test_registration_plan_reference_is_preserved(self):
        context = self.new_context()
        approval_request, plan, registration_request = self.chain()
        self.manager.approve(registration_request["request_id"])
        decision = self.decide(
            human_approval_request=approval_request, registration_plan=plan,
            registration_request_id=registration_request["request_id"],
            approval_manager=self.manager)
        self.assertEqual(decision["decision"], DECISION_REGISTER)

        context = apply_successful_transition(context, decision)
        self.assertEqual(
            context["registration_plan_reference"],
            decision["lifecycle_state"]["registration_plan"])

    def test_build_and_implementation_spec_references_are_preserved(self):
        context = self.new_context()
        decision = self.decide(build_result=self.build_result())
        context = apply_successful_transition(
            context, decision, build_spec=self.build_spec,
            implementation_spec={"capability_name": CODE_CHANGE_PLAN_NAME})
        self.assertEqual(context["build_spec_reference"], self.build_spec)
        self.assertEqual(
            context["implementation_spec_reference"], {"capability_name": CODE_CHANGE_PLAN_NAME})

        # A later transition that doesn't re-supply either spec must not
        # erase the ones already on record.
        next_decision = self.decide(
            build_result=self.build_result(), apply_request=self.apply_request())
        context = apply_successful_transition(context, next_decision)
        self.assertEqual(context["build_spec_reference"], self.build_spec)
        self.assertEqual(
            context["implementation_spec_reference"], {"capability_name": CODE_CHANGE_PLAN_NAME})


# --------------------------------------------------------------------
# Coordinator integration: resume / advance
# --------------------------------------------------------------------
class CoordinatorResumeTests(ContextSetup):
    def test_coordinator_can_resume_from_an_existing_context(self):
        context = self.new_context()
        decision = self.decide(
            build_result=self.build_result(), apply_request=self.apply_request())
        context = apply_successful_transition(context, decision)
        self.store.save(context)

        reloaded = self.store.load(UPGRADE_REQUEST_ID)
        resumed = self.coordinator.resume(reloaded)
        self.assertEqual(resumed["decision"], DECISION_TEST)
        self.assertEqual(resumed["lifecycle_state"], decision["lifecycle_state"])

    def test_resume_on_a_fresh_context_returns_none(self):
        context = self.new_context()
        self.assertIsNone(self.coordinator.resume(context))

    def test_resume_never_recomputes_or_restarts_a_completed_stage(self):
        """Resuming reads only what is already stored - it must not
        require (or use) any raw stage result a second time."""
        context = self.new_context()
        decision = self.decide(build_result=self.build_result())
        context = apply_successful_transition(context, decision)

        # No build_result, apply_request, etc. supplied here at all -
        # if resume needed to re-derive anything it would come back
        # INVALID instead of the already-recorded VALIDATE.
        resumed = self.coordinator.resume(context)
        self.assertEqual(resumed["decision"], DECISION_VALIDATE)

    def test_advance_computes_and_folds_a_decision_into_the_context(self):
        context = self.store.get_or_create(UPGRADE_REQUEST_ID, capability_name=CODE_CHANGE_PLAN_NAME)
        new_context, decision = self.coordinator.advance(
            context, build_result=self.build_result())
        self.assertEqual(decision["decision"], DECISION_VALIDATE)
        self.assertEqual(new_context["current_action"], DECISION_VALIDATE)
        self.store.save(new_context)

        new_context_2, decision_2 = self.coordinator.advance(
            self.store.load(UPGRADE_REQUEST_ID),
            build_result=self.build_result(), apply_request=self.apply_request())
        self.assertEqual(decision_2["decision"], DECISION_TEST)
        self.assertEqual(new_context_2["last_completed_action"], DECISION_VALIDATE)

    def test_advance_with_explicit_error_preserves_state_without_deciding(self):
        context = self.store.get_or_create(UPGRADE_REQUEST_ID, capability_name=CODE_CHANGE_PLAN_NAME)
        context, _ = self.coordinator.advance(context, build_result=self.build_result())
        before_action = context["current_action"]

        after, decision = self.coordinator.advance(context, error="disk was full mid-write")
        self.assertIsNone(decision)
        self.assertEqual(after["current_action"], before_action)
        self.assertEqual(after["last_error"], "disk was full mid-write")


# --------------------------------------------------------------------
# VERIFIED never becomes ACTIVE; persistence never executes/activates
# --------------------------------------------------------------------
class SafetyTests(ContextSetup):
    def test_verified_is_recorded_as_completed_never_active(self):
        context = self.new_context()
        _, _, _, result, verification = self.verified()
        decision = self.decide(registration_result=result, verification_result=verification)
        self.assertEqual(decision["lifecycle_status"], LIFECYCLE_VERIFIED)
        self.assertEqual(decision["decision"], DECISION_COMPLETED)

        context = apply_successful_transition(context, decision)
        self.assertEqual(context["current_action"], DECISION_COMPLETED)
        self.assertNotEqual(context["current_action"], "ACTIVE")
        for field in CONTEXT_FIELDS:
            self.assertNotEqual(context.get(field), "ACTIVE")

    def test_capability_is_not_enabled_by_persisting_or_resuming_a_verified_context(self):
        context = self.new_context()
        _, _, _, result, verification = self.verified()
        decision = self.decide(registration_result=result, verification_result=verification)
        context = apply_successful_transition(context, decision)
        self.store.save(context)

        reloaded = self.store.load(UPGRADE_REQUEST_ID)
        self.coordinator.resume(reloaded)

        # capability_system is the real, shared fixture from
        # CoordinatorSetup/Setup - registering/verifying it already
        # only ever registers it *disabled*; saving/loading/resuming
        # the context must not be a second path to enabling it.
        registered = [
            entry for entry in self.capability_system.all()
            if entry.get("name") == CODE_CHANGE_PLAN_NAME
        ]
        for entry in registered:
            self.assertFalse(entry.get("enabled"))

    def test_context_module_never_imports_execution_or_approval_action_surfaces(self):
        """This module's only job is bookkeeping - see module
        docstring's safety boundary. It must never import anything
        capable of approving, rejecting, registering, or executing a
        capability."""
        import ast
        import self_upgrade.self_upgrade_execution_context as module

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
