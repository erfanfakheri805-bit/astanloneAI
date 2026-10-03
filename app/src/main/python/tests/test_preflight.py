"""
Tests for PreflightValidator (execution/preflight.py), including its
integration into ExecutionEngine.execute_step/retry_step.

Covers: a valid READY step, a non-READY step, a missing dependency, an
unavailable capability, a missing plan, a missing step, that the
handler is never called when preflight fails, that retry_step also
goes through preflight, that a genuinely valid execution still works
end to end, and that preflight itself never has any side effects
(never writes a PlanStep's status, never touches the capability
registry).

Run directly:
    python -m unittest tests.test_preflight -v
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
from planning.plan import (
    STATUS_PENDING, STATUS_READY, STATUS_BLOCKED, STATUS_COMPLETED, STATUS_FAILED,
)
from execution.execution_engine import ExecutionEngine
from execution.execution_result import (
    STATUS_COMPLETED as EXEC_STATUS_COMPLETED, STATUS_FAILED as EXEC_STATUS_FAILED,
)
from execution.preflight import (
    PreflightValidator,
    PreflightResult,
    CHECK_PLAN_EXISTS,
    CHECK_STEP_EXISTS,
    CHECK_STEP_READY,
    CHECK_DEPENDENCIES_SATISFIED,
    CHECK_CAPABILITIES_AVAILABLE,
)


class FakeCapabilitySystem:
    """Minimal stand-in for capabilities.capability_system.CapabilitySystem
    - exposes only the read-only `.all()` registry lookup
    PlanManager._unavailable_capabilities/_capability_registry_lookup
    actually use, same convention already used by
    tests/test_execution_engine.py's own FakeCapabilitySystem."""

    def __init__(self, registered=None):
        # name -> enabled
        self._registered = dict(registered) if registered else {}

    def all(self):
        return [
            {"name": name, "enabled": enabled, "status": "enabled" if enabled else "disabled"}
            for name, enabled in self._registered.items()
        ]


class TestPreflightBase(unittest.TestCase):
    def setUp(self):
        self.goals = GoalManager()
        self.plans = PlanManager(self.goals)
        self.validator = PreflightValidator(self.plans)
        self.goal = self.goals.create_goal("Ship a small feature")
        self.plan = self.plans.create_plan(self.goal.goal_id)

    def _ready_step(self, description="Do the thing", **kwargs):
        step = self.plans.add_step(self.plan.plan_id, description, **kwargs)
        self.plans.update_step_status(self.plan.plan_id, step.step_id, STATUS_READY)
        return step


class TestConstruction(unittest.TestCase):
    def test_requires_a_plan_manager_instance(self):
        with self.assertRaises(TypeError):
            PreflightValidator("not-a-plan-manager")


class TestValidReadyStep(TestPreflightBase):
    def test_valid_ready_step_passes(self):
        step = self._ready_step()
        result = self.validator.validate_step(self.plan.plan_id, step.step_id)

        self.assertIsInstance(result, PreflightResult)
        self.assertTrue(result.valid)
        self.assertEqual(result.failed_checks, [])

    def test_result_carries_plan_and_step_ids(self):
        step = self._ready_step()
        result = self.validator.validate_step(self.plan.plan_id, step.step_id)

        self.assertEqual(result.plan_id, self.plan.plan_id)
        self.assertEqual(result.step_id, step.step_id)

    def test_to_dict_reports_every_expected_field(self):
        step = self._ready_step()
        result = self.validator.validate_step(self.plan.plan_id, step.step_id)
        data = result.to_dict()

        self.assertEqual(
            set(data.keys()),
            {"plan_id", "step_id", "valid", "failed_checks", "warnings"},
        )
        self.assertTrue(data["valid"])

    def test_ready_step_with_satisfied_dependency_and_available_capability_passes(self):
        upstream = self._ready_step("Upstream")
        self.plans.update_step_status(self.plan.plan_id, upstream.step_id, STATUS_COMPLETED)
        downstream = self.plans.add_step(
            self.plan.plan_id, "Downstream",
            dependencies=[upstream.step_id],
            required_capabilities=["send_email"],
        )
        caps = FakeCapabilitySystem(registered={"send_email": True})
        self.plans.refresh_step_status(self.plan.plan_id, downstream.step_id, caps)
        self.assertEqual(downstream.status, STATUS_READY)

        result = self.validator.validate_step(self.plan.plan_id, downstream.step_id, caps)
        self.assertTrue(result.valid)


class TestNonReadyStep(TestPreflightBase):
    def test_pending_step_fails_step_ready_check(self):
        step = self.plans.add_step(self.plan.plan_id, "Not ready yet")

        result = self.validator.validate_step(self.plan.plan_id, step.step_id)

        self.assertFalse(result.valid)
        checks = [fc["check"] for fc in result.failed_checks]
        self.assertIn(CHECK_STEP_READY, checks)
        reason = next(fc["reason"] for fc in result.failed_checks if fc["check"] == CHECK_STEP_READY)
        self.assertIn(STATUS_PENDING, reason)

    def test_blocked_step_fails_step_ready_check(self):
        step = self.plans.add_step(self.plan.plan_id, "Waiting")
        self.plans.update_step_status(self.plan.plan_id, step.step_id, STATUS_BLOCKED)

        result = self.validator.validate_step(self.plan.plan_id, step.step_id)

        self.assertFalse(result.valid)
        checks = [fc["check"] for fc in result.failed_checks]
        self.assertIn(CHECK_STEP_READY, checks)

    def test_completed_step_fails_step_ready_check(self):
        step = self._ready_step()
        self.plans.update_step_status(self.plan.plan_id, step.step_id, STATUS_COMPLETED)

        result = self.validator.validate_step(self.plan.plan_id, step.step_id)

        self.assertFalse(result.valid)
        checks = [fc["check"] for fc in result.failed_checks]
        self.assertIn(CHECK_STEP_READY, checks)


class TestMissingDependency(TestPreflightBase):
    def test_unresolved_dependency_fails_dependencies_satisfied_check(self):
        upstream = self.plans.add_step(self.plan.plan_id, "Upstream")  # still PENDING
        downstream = self.plans.add_step(
            self.plan.plan_id, "Downstream", dependencies=[upstream.step_id]
        )
        # Force it to READY directly (bypassing refresh_step_status) so
        # only the dependency check - not the status check - is being
        # exercised here.
        self.plans.update_step_status(self.plan.plan_id, downstream.step_id, STATUS_READY)

        result = self.validator.validate_step(self.plan.plan_id, downstream.step_id)

        self.assertFalse(result.valid)
        checks = [fc["check"] for fc in result.failed_checks]
        self.assertIn(CHECK_DEPENDENCIES_SATISFIED, checks)
        reason = next(
            fc["reason"] for fc in result.failed_checks
            if fc["check"] == CHECK_DEPENDENCIES_SATISFIED
        )
        self.assertIn(upstream.step_id, reason)

    def test_dependency_on_a_nonexistent_step_id_also_fails(self):
        step = self.plans.add_step(
            self.plan.plan_id, "Depends on nothing real", dependencies=["no-such-step"]
        )
        self.plans.update_step_status(self.plan.plan_id, step.step_id, STATUS_READY)

        result = self.validator.validate_step(self.plan.plan_id, step.step_id)

        self.assertFalse(result.valid)
        checks = [fc["check"] for fc in result.failed_checks]
        self.assertIn(CHECK_DEPENDENCIES_SATISFIED, checks)


class TestUnavailableCapability(TestPreflightBase):
    def test_missing_registration_fails_capabilities_available_check(self):
        step = self.plans.add_step(
            self.plan.plan_id, "Needs a capability", required_capabilities=["send_email"]
        )
        self.plans.update_step_status(self.plan.plan_id, step.step_id, STATUS_READY)
        caps = FakeCapabilitySystem()  # nothing registered

        result = self.validator.validate_step(self.plan.plan_id, step.step_id, caps)

        self.assertFalse(result.valid)
        checks = [fc["check"] for fc in result.failed_checks]
        self.assertIn(CHECK_CAPABILITIES_AVAILABLE, checks)
        reason = next(
            fc["reason"] for fc in result.failed_checks
            if fc["check"] == CHECK_CAPABILITIES_AVAILABLE
        )
        self.assertIn("send_email", reason)

    def test_disabled_capability_fails_capabilities_available_check(self):
        step = self.plans.add_step(
            self.plan.plan_id, "Needs a capability", required_capabilities=["send_email"]
        )
        self.plans.update_step_status(self.plan.plan_id, step.step_id, STATUS_READY)
        caps = FakeCapabilitySystem(registered={"send_email": False})

        result = self.validator.validate_step(self.plan.plan_id, step.step_id, caps)

        self.assertFalse(result.valid)
        checks = [fc["check"] for fc in result.failed_checks]
        self.assertIn(CHECK_CAPABILITIES_AVAILABLE, checks)

    def test_missing_capability_system_skips_check_and_adds_warning_instead(self):
        """No capability_system means the check can't be answered, not
        that every requirement is treated as unavailable - same
        "dependency-only behavior" contract
        PlanManager._unavailable_capabilities already has."""
        step = self.plans.add_step(
            self.plan.plan_id, "Needs a capability", required_capabilities=["send_email"]
        )
        self.plans.update_step_status(self.plan.plan_id, step.step_id, STATUS_READY)

        result = self.validator.validate_step(self.plan.plan_id, step.step_id)

        checks = [fc["check"] for fc in result.failed_checks]
        self.assertNotIn(CHECK_CAPABILITIES_AVAILABLE, checks)
        self.assertTrue(result.valid)
        self.assertTrue(result.warnings)
        self.assertIn("send_email", result.warnings[0])


class TestMissingPlan(TestPreflightBase):
    def test_unknown_plan_fails_plan_exists_check_only(self):
        result = self.validator.validate_step("does-not-exist", "some-step")

        self.assertFalse(result.valid)
        self.assertEqual(len(result.failed_checks), 1)
        self.assertEqual(result.failed_checks[0]["check"], CHECK_PLAN_EXISTS)
        self.assertIn("does-not-exist", result.failed_checks[0]["reason"])


class TestMissingStep(TestPreflightBase):
    def test_unknown_step_fails_step_exists_check_only(self):
        result = self.validator.validate_step(self.plan.plan_id, "no-such-step")

        self.assertFalse(result.valid)
        self.assertEqual(len(result.failed_checks), 1)
        self.assertEqual(result.failed_checks[0]["check"], CHECK_STEP_EXISTS)
        self.assertIn("no-such-step", result.failed_checks[0]["reason"])


class TestMultipleFailedChecksAtOnce(TestPreflightBase):
    def test_non_ready_step_with_unresolved_dependency_reports_both(self):
        upstream = self.plans.add_step(self.plan.plan_id, "Upstream")  # PENDING
        downstream = self.plans.add_step(
            self.plan.plan_id, "Downstream", dependencies=[upstream.step_id]
        )
        # Leave downstream PENDING (never forced to READY) - both the
        # status check and the dependency check should fail.
        result = self.validator.validate_step(self.plan.plan_id, downstream.step_id)

        self.assertFalse(result.valid)
        checks = {fc["check"] for fc in result.failed_checks}
        self.assertIn(CHECK_STEP_READY, checks)
        self.assertIn(CHECK_DEPENDENCIES_SATISFIED, checks)


# ----------------------------------------------------------------------
# Integration with ExecutionEngine
# ----------------------------------------------------------------------
class TestExecutionEnginePreflightBase(unittest.TestCase):
    def setUp(self):
        self.goals = GoalManager()
        self.plans = PlanManager(self.goals)
        self.engine = ExecutionEngine(self.plans)
        self.goal = self.goals.create_goal("Ship a small feature")
        self.plan = self.plans.create_plan(self.goal.goal_id)

    def _ready_step(self, description="Do the thing", **kwargs):
        step = self.plans.add_step(self.plan.plan_id, description, **kwargs)
        self.plans.update_step_status(self.plan.plan_id, step.step_id, STATUS_READY)
        return step


class TestHandlerNotCalledWhenPreflightFails(TestExecutionEnginePreflightBase):
    def test_unresolved_dependency_blocks_execution_without_calling_handler(self):
        upstream = self.plans.add_step(self.plan.plan_id, "Upstream")  # PENDING
        downstream = self.plans.add_step(
            self.plan.plan_id, "Downstream", dependencies=[upstream.step_id]
        )
        self.plans.update_step_status(self.plan.plan_id, downstream.step_id, STATUS_READY)
        called = []

        def handler(plan_step):
            called.append(True)
            return "should not run"

        result = self.engine.execute_step(self.plan.plan_id, downstream.step_id, handler)

        self.assertEqual(called, [])
        self.assertEqual(result.status, EXEC_STATUS_FAILED)

    def test_unavailable_capability_blocks_execution_without_calling_handler(self):
        step = self.plans.add_step(
            self.plan.plan_id, "Needs a capability", required_capabilities=["send_email"]
        )
        self.plans.update_step_status(self.plan.plan_id, step.step_id, STATUS_READY)
        caps = FakeCapabilitySystem()  # nothing registered
        called = []

        def handler(plan_step):
            called.append(True)
            return "should not run"

        result = self.engine.execute_step(
            self.plan.plan_id, step.step_id, handler, capability_system=caps
        )

        self.assertEqual(called, [])
        self.assertEqual(result.status, EXEC_STATUS_FAILED)

    def test_preflight_failure_result_carries_structured_preflight_data(self):
        step = self.plans.add_step(
            self.plan.plan_id, "Needs a capability", required_capabilities=["send_email"]
        )
        self.plans.update_step_status(self.plan.plan_id, step.step_id, STATUS_READY)
        caps = FakeCapabilitySystem()

        result = self.engine.execute_step(
            self.plan.plan_id, step.step_id, lambda s: "ok", capability_system=caps
        )

        self.assertIn("preflight", result.metadata)
        self.assertFalse(result.metadata["preflight"]["valid"])
        checks = [fc["check"] for fc in result.metadata["preflight"]["failed_checks"]]
        self.assertIn(CHECK_CAPABILITIES_AVAILABLE, checks)


class TestValidExecutionStillWorks(TestExecutionEnginePreflightBase):
    def test_ready_step_with_no_dependencies_or_capabilities_still_executes(self):
        step = self._ready_step()

        result = self.engine.execute_step(self.plan.plan_id, step.step_id, lambda s: "ok")

        self.assertEqual(result.status, EXEC_STATUS_COMPLETED)
        self.assertEqual(step.status, STATUS_COMPLETED)

    def test_ready_step_with_satisfied_dependency_and_available_capability_executes(self):
        upstream = self._ready_step("Upstream")
        self.engine.execute_step(self.plan.plan_id, upstream.step_id, lambda s: "ok")
        downstream = self.plans.add_step(
            self.plan.plan_id, "Downstream",
            dependencies=[upstream.step_id],
            required_capabilities=["send_email"],
        )
        caps = FakeCapabilitySystem(registered={"send_email": True})
        self.plans.refresh_step_status(self.plan.plan_id, downstream.step_id, caps)
        self.assertEqual(downstream.status, STATUS_READY)

        result = self.engine.execute_step(
            self.plan.plan_id, downstream.step_id, lambda s: "sent", capability_system=caps
        )

        self.assertEqual(result.status, EXEC_STATUS_COMPLETED)
        self.assertEqual(downstream.status, STATUS_COMPLETED)


class TestRetryAlsoUsesPreflight(TestExecutionEnginePreflightBase):
    def _failed_step(self, description="Will fail then retry", **kwargs):
        step = self._ready_step(description, **kwargs)

        def failing_handler(plan_step):
            raise ValueError("boom")

        self.engine.execute_step(self.plan.plan_id, step.step_id, failing_handler)
        self.assertEqual(step.status, STATUS_FAILED)
        return step

    def test_retry_blocked_when_a_required_capability_became_unavailable(self):
        step = self.plans.add_step(
            self.plan.plan_id, "Needs a capability", required_capabilities=["send_email"]
        )
        self.plans.update_step_status(self.plan.plan_id, step.step_id, STATUS_READY)
        caps = FakeCapabilitySystem(registered={"send_email": True})

        def failing(plan_step):
            raise RuntimeError("first attempt broke")

        self.engine.execute_step(
            self.plan.plan_id, step.step_id, failing, capability_system=caps
        )
        self.assertEqual(step.status, STATUS_FAILED)

        # The capability got disabled while the step sat FAILED.
        caps._registered["send_email"] = False
        called = []

        def should_not_run(plan_step):
            called.append(True)
            return "should not run"

        result = self.engine.retry_step(
            self.plan.plan_id, step.step_id, should_not_run, capability_system=caps
        )

        self.assertEqual(called, [])
        self.assertEqual(result.status, EXEC_STATUS_FAILED)
        # The failed READY-flip must be undone - the step is left
        # FAILED, not stuck READY (requirement 9).
        self.assertEqual(step.status, STATUS_FAILED)

    def test_retry_blocked_when_a_dependency_became_unresolved(self):
        upstream = self._ready_step("Upstream")
        downstream = self.plans.add_step(
            self.plan.plan_id, "Downstream", dependencies=[upstream.step_id]
        )
        self.plans.refresh_step_status(self.plan.plan_id, downstream.step_id)
        self.engine.execute_step(self.plan.plan_id, upstream.step_id, lambda s: "ok")
        self.assertEqual(downstream.status, STATUS_READY)

        def failing(plan_step):
            raise RuntimeError("first attempt broke")

        self.engine.execute_step(self.plan.plan_id, downstream.step_id, failing)
        self.assertEqual(downstream.status, STATUS_FAILED)

        # Upstream regresses to FAILED, so downstream's dependency is
        # no longer resolved.
        upstream.set_status(STATUS_FAILED)
        called = []

        def should_not_run(plan_step):
            called.append(True)
            return "should not run"

        result = self.engine.retry_step(self.plan.plan_id, downstream.step_id, should_not_run)

        self.assertEqual(called, [])
        self.assertEqual(result.status, EXEC_STATUS_FAILED)
        self.assertEqual(downstream.status, STATUS_FAILED)

    def test_retry_still_succeeds_when_preflight_passes(self):
        step = self._failed_step()

        result = self.engine.retry_step(self.plan.plan_id, step.step_id, lambda s: "fixed")

        self.assertEqual(result.status, EXEC_STATUS_COMPLETED)
        self.assertEqual(step.status, STATUS_COMPLETED)


class TestNoSideEffects(TestPreflightBase):
    def test_validate_step_never_changes_the_steps_status(self):
        step = self.plans.add_step(self.plan.plan_id, "Not ready yet")  # PENDING
        self.validator.validate_step(self.plan.plan_id, step.step_id)
        self.assertEqual(step.status, STATUS_PENDING)

        blocked = self.plans.add_step(self.plan.plan_id, "Blocked", dependencies=["ghost"])
        self.plans.update_step_status(self.plan.plan_id, blocked.step_id, STATUS_BLOCKED)
        self.validator.validate_step(self.plan.plan_id, blocked.step_id)
        self.assertEqual(blocked.status, STATUS_BLOCKED)

    def test_validate_step_never_calls_update_step_status(self):
        step = self._ready_step()
        calls = []
        original = self.plans.update_step_status

        def spy(*args, **kwargs):
            calls.append(args[1:])
            return original(*args, **kwargs)

        self.plans.update_step_status = spy
        try:
            self.validator.validate_step(self.plan.plan_id, step.step_id)
        finally:
            self.plans.update_step_status = original
        self.assertEqual(calls, [])

    def test_validate_step_never_writes_to_the_capability_registry(self):
        step = self.plans.add_step(
            self.plan.plan_id, "Needs a capability", required_capabilities=["send_email"]
        )
        self.plans.update_step_status(self.plan.plan_id, step.step_id, STATUS_READY)
        caps = FakeCapabilitySystem(registered={"send_email": False})
        before = caps.all()

        self.validator.validate_step(self.plan.plan_id, step.step_id, caps)

        self.assertEqual(caps.all(), before)

    def test_validate_step_never_calls_a_handler(self):
        """PreflightValidator has no handler concept at all - there's
        nothing to call, and nothing here ever does."""
        step = self._ready_step()
        # No handler is even passed - validate_step's signature has no
        # such parameter, so this simply demonstrates a valid result
        # requires nothing handler-shaped to produce.
        result = self.validator.validate_step(self.plan.plan_id, step.step_id)
        self.assertTrue(result.valid)

    def test_does_not_change_blocked_step_to_ready(self):
        """Requirement 11: nothing about preflight ever promotes a
        BLOCKED step to READY on its own."""
        upstream = self.plans.add_step(self.plan.plan_id, "Upstream")  # PENDING
        downstream = self.plans.add_step(
            self.plan.plan_id, "Downstream", dependencies=[upstream.step_id]
        )
        self.plans.refresh_step_status(self.plan.plan_id, downstream.step_id)
        self.assertEqual(downstream.status, STATUS_BLOCKED)

        self.validator.validate_step(self.plan.plan_id, downstream.step_id)

        self.assertEqual(downstream.status, STATUS_BLOCKED)


if __name__ == "__main__":
    unittest.main()
