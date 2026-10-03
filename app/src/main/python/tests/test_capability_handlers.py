"""
Tests for CapabilityHandlerRegistry (execution/capability_handlers.py)
and its integration into ExecutionEngine.execute_capability_step
(execution/execution_engine.py).

Covers: registering a valid handler, rejecting invalid handlers,
duplicate registration (and the explicit `replace` escape hatch),
unregistering, handler lookup (`get`/`has`), listing registered
handlers, successful capability execution, a missing handler being
refused, multiple capabilities executing in deterministic order,
handler failure, remaining handlers not running after a failure, that
preflight is still enforced ahead of any handler lookup, and that
execution history stays correct for this new path.

Run directly:
    python -m unittest tests.test_capability_handlers -v
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
from planning.plan import STATUS_READY, STATUS_COMPLETED, STATUS_FAILED
from execution.execution_engine import ExecutionEngine
from execution.execution_result import (
    STATUS_COMPLETED as EXEC_STATUS_COMPLETED, STATUS_FAILED as EXEC_STATUS_FAILED,
)
from execution.capability_handlers import CapabilityHandlerRegistry, CapabilityReadinessResult


class FakeCapabilitySystem:
    """Minimal stand-in for capabilities.capability_system.CapabilitySystem
    - exposes only the read-only `.all()` registry lookup PreflightValidator
    actually uses, same convention already used by
    tests/test_preflight.py's own FakeCapabilitySystem."""

    def __init__(self, registered=None):
        self._registered = dict(registered) if registered else {}

    def all(self):
        return [
            {"name": name, "enabled": enabled, "status": "enabled" if enabled else "disabled"}
            for name, enabled in self._registered.items()
        ]


# ----------------------------------------------------------------------
# CapabilityHandlerRegistry on its own
# ----------------------------------------------------------------------
class TestRegisterValidHandler(unittest.TestCase):
    def setUp(self):
        self.registry = CapabilityHandlerRegistry()

    def test_register_stores_the_handler(self):
        def handler(step):
            return "ok"

        self.registry.register("send_email", handler)
        self.assertIs(self.registry.get("send_email"), handler)

    def test_register_returns_the_handler(self):
        def handler(step):
            return "ok"

        returned = self.registry.register("send_email", handler)
        self.assertIs(returned, handler)

    def test_register_does_not_call_the_handler(self):
        calls = []

        def handler(step):
            calls.append(step)
            return "ok"

        self.registry.register("send_email", handler)
        self.assertEqual(calls, [])


class TestRejectInvalidHandlers(unittest.TestCase):
    def setUp(self):
        self.registry = CapabilityHandlerRegistry()

    def test_rejects_none_handler(self):
        with self.assertRaises(TypeError):
            self.registry.register("send_email", None)

    def test_rejects_non_callable_handler(self):
        with self.assertRaises(TypeError):
            self.registry.register("send_email", "not-callable")

    def test_rejects_empty_capability_name(self):
        with self.assertRaises(ValueError):
            self.registry.register("", lambda step: "ok")

    def test_rejects_whitespace_only_capability_name(self):
        with self.assertRaises(ValueError):
            self.registry.register("   ", lambda step: "ok")

    def test_rejects_none_capability_name(self):
        with self.assertRaises(ValueError):
            self.registry.register(None, lambda step: "ok")

    def test_a_rejected_registration_stores_nothing(self):
        with self.assertRaises(TypeError):
            self.registry.register("send_email", None)
        self.assertFalse(self.registry.has("send_email"))


class TestDuplicateRegistration(unittest.TestCase):
    def setUp(self):
        self.registry = CapabilityHandlerRegistry()
        self.original = lambda step: "original"
        self.registry.register("send_email", self.original)

    def test_registering_the_same_name_again_raises(self):
        with self.assertRaises(ValueError):
            self.registry.register("send_email", lambda step: "new")

    def test_duplicate_registration_leaves_the_original_handler_in_place(self):
        with self.assertRaises(ValueError):
            self.registry.register("send_email", lambda step: "new")
        self.assertIs(self.registry.get("send_email"), self.original)

    def test_replace_explicitly_overwrites_an_existing_handler(self):
        new_handler = lambda step: "new"
        self.registry.replace("send_email", new_handler)
        self.assertIs(self.registry.get("send_email"), new_handler)

    def test_replace_also_works_for_a_brand_new_name(self):
        handler = lambda step: "fresh"
        self.registry.replace("brand_new", handler)
        self.assertIs(self.registry.get("brand_new"), handler)

    def test_replace_still_rejects_a_non_callable_handler(self):
        with self.assertRaises(TypeError):
            self.registry.replace("send_email", "nope")


class TestUnregistering(unittest.TestCase):
    def setUp(self):
        self.registry = CapabilityHandlerRegistry()
        self.registry.register("send_email", lambda step: "ok")

    def test_unregister_removes_the_handler(self):
        self.registry.unregister("send_email")
        self.assertFalse(self.registry.has("send_email"))
        self.assertIsNone(self.registry.get("send_email"))

    def test_unregister_returns_true_when_something_was_removed(self):
        self.assertTrue(self.registry.unregister("send_email"))

    def test_unregister_returns_false_for_an_unknown_name(self):
        self.assertFalse(self.registry.unregister("never_registered"))

    def test_unregister_never_raises_for_an_unknown_name(self):
        try:
            self.registry.unregister("never_registered")
        except Exception as exc:  # pragma: no cover - should never happen
            self.fail(f"unregister raised for an unknown name: {exc}")

    def test_after_unregistering_the_name_can_be_registered_again(self):
        self.registry.unregister("send_email")
        new_handler = lambda step: "new"
        self.registry.register("send_email", new_handler)
        self.assertIs(self.registry.get("send_email"), new_handler)


class TestHandlerLookup(unittest.TestCase):
    def setUp(self):
        self.registry = CapabilityHandlerRegistry()

    def test_get_returns_none_for_an_unregistered_capability(self):
        self.assertIsNone(self.registry.get("send_email"))

    def test_has_returns_false_for_an_unregistered_capability(self):
        self.assertFalse(self.registry.has("send_email"))

    def test_has_returns_true_once_registered(self):
        self.registry.register("send_email", lambda step: "ok")
        self.assertTrue(self.registry.has("send_email"))

    def test_get_and_has_never_raise_for_a_non_string_name(self):
        try:
            self.assertIsNone(self.registry.get(None))
            self.assertFalse(self.registry.has(None))
        except Exception as exc:  # pragma: no cover - should never happen
            self.fail(f"get/has raised for a non-string name: {exc}")


class TestListingHandlers(unittest.TestCase):
    def setUp(self):
        self.registry = CapabilityHandlerRegistry()

    def test_list_registered_is_empty_for_a_fresh_registry(self):
        self.assertEqual(self.registry.list_registered(), [])

    def test_list_registered_reflects_registrations_in_order(self):
        self.registry.register("send_email", lambda step: "ok")
        self.registry.register("send_sms", lambda step: "ok")
        self.assertEqual(self.registry.list_registered(), ["send_email", "send_sms"])

    def test_list_registered_reflects_unregistration(self):
        self.registry.register("send_email", lambda step: "ok")
        self.registry.register("send_sms", lambda step: "ok")
        self.registry.unregister("send_email")
        self.assertEqual(self.registry.list_registered(), ["send_sms"])


# ----------------------------------------------------------------------
# ExecutionEngine.execute_capability_step
# ----------------------------------------------------------------------
class TestExecuteCapabilityStepBase(unittest.TestCase):
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


class TestSuccessfulCapabilityExecution(TestExecuteCapabilityStepBase):
    def test_registered_handler_is_used_and_result_is_completed(self):
        step = self._ready_step(required_capabilities=["send_email"])
        self.engine.capability_handlers.register(
            "send_email", lambda plan_step: f"sent for {plan_step.step_id}"
        )

        result = self.engine.execute_capability_step(self.plan.plan_id, step.step_id)

        self.assertEqual(result.status, EXEC_STATUS_COMPLETED)
        self.assertEqual(result.output, {"send_email": f"sent for {step.step_id}"})
        self.assertIsNone(result.error)

    def test_successful_execution_syncs_the_plan_step_to_completed(self):
        step = self._ready_step(required_capabilities=["send_email"])
        self.engine.capability_handlers.register("send_email", lambda plan_step: "ok")

        self.engine.execute_capability_step(self.plan.plan_id, step.step_id)

        self.assertEqual(self.plans.get_step(self.plan.plan_id, step.step_id).status,
                          STATUS_COMPLETED)

    def test_a_step_with_no_required_capabilities_completes_with_empty_output(self):
        step = self._ready_step()

        result = self.engine.execute_capability_step(self.plan.plan_id, step.step_id)

        self.assertEqual(result.status, EXEC_STATUS_COMPLETED)
        self.assertEqual(result.output, {})


class TestMissingHandler(TestExecuteCapabilityStepBase):
    def test_missing_handler_is_refused_with_a_failed_result(self):
        step = self._ready_step(required_capabilities=["send_email"])

        result = self.engine.execute_capability_step(self.plan.plan_id, step.step_id)

        self.assertEqual(result.status, EXEC_STATUS_FAILED)
        self.assertIn("send_email", result.error)

    def test_missing_handler_never_touches_the_plan_step(self):
        step = self._ready_step(required_capabilities=["send_email"])

        self.engine.execute_capability_step(self.plan.plan_id, step.step_id)

        self.assertEqual(self.plans.get_step(self.plan.plan_id, step.step_id).status,
                          STATUS_READY)

    def test_missing_handler_means_no_registered_handler_is_called_either(self):
        step = self._ready_step(required_capabilities=["send_email", "send_sms"])
        calls = []
        self.engine.capability_handlers.register(
            "send_sms", lambda plan_step: calls.append("send_sms")
        )
        # "send_email" has no handler - refuse the whole step, even
        # though "send_sms" does have one.
        self.engine.execute_capability_step(self.plan.plan_id, step.step_id)
        self.assertEqual(calls, [])


class TestMultipleCapabilities(TestExecuteCapabilityStepBase):
    def test_all_handlers_run_and_are_collected_into_output(self):
        step = self._ready_step(required_capabilities=["send_email", "send_sms"])
        self.engine.capability_handlers.register("send_email", lambda plan_step: "emailed")
        self.engine.capability_handlers.register("send_sms", lambda plan_step: "texted")

        result = self.engine.execute_capability_step(self.plan.plan_id, step.step_id)

        self.assertEqual(result.status, EXEC_STATUS_COMPLETED)
        self.assertEqual(result.output, {"send_email": "emailed", "send_sms": "texted"})


class TestDeterministicExecutionOrder(TestExecuteCapabilityStepBase):
    def test_handlers_run_in_required_capabilities_order(self):
        step = self._ready_step(required_capabilities=["third", "first", "second"])
        order = []
        self.engine.capability_handlers.register(
            "third", lambda plan_step: order.append("third")
        )
        self.engine.capability_handlers.register(
            "first", lambda plan_step: order.append("first")
        )
        self.engine.capability_handlers.register(
            "second", lambda plan_step: order.append("second")
        )

        self.engine.execute_capability_step(self.plan.plan_id, step.step_id)

        self.assertEqual(order, ["third", "first", "second"])


class TestHandlerFailure(TestExecuteCapabilityStepBase):
    def test_a_raising_handler_produces_a_failed_result_with_safe_error(self):
        step = self._ready_step(required_capabilities=["send_email"])
        self.engine.capability_handlers.register(
            "send_email", lambda plan_step: (_ for _ in ()).throw(ValueError("boom"))
        )

        result = self.engine.execute_capability_step(self.plan.plan_id, step.step_id)

        self.assertEqual(result.status, EXEC_STATUS_FAILED)
        self.assertIn("ValueError", result.error)
        self.assertIn("boom", result.error)

    def test_a_raising_handler_moves_the_plan_step_to_failed(self):
        step = self._ready_step(required_capabilities=["send_email"])
        self.engine.capability_handlers.register(
            "send_email", lambda plan_step: (_ for _ in ()).throw(RuntimeError("kaboom"))
        )

        self.engine.execute_capability_step(self.plan.plan_id, step.step_id)

        self.assertEqual(self.plans.get_step(self.plan.plan_id, step.step_id).status,
                          STATUS_FAILED)

    def test_remaining_handlers_are_not_executed_after_a_failure(self):
        step = self._ready_step(
            required_capabilities=["send_email", "send_sms", "send_push"]
        )
        calls = []

        def failing_handler(plan_step):
            calls.append("send_email")
            raise ValueError("boom")

        def should_not_run(plan_step):
            calls.append("should_not_run")
            return "ok"

        self.engine.capability_handlers.register("send_email", failing_handler)
        self.engine.capability_handlers.register("send_sms", should_not_run)
        self.engine.capability_handlers.register("send_push", should_not_run)

        result = self.engine.execute_capability_step(self.plan.plan_id, step.step_id)

        self.assertEqual(result.status, EXEC_STATUS_FAILED)
        self.assertEqual(calls, ["send_email"])


class TestPreflightStillEnforced(TestExecuteCapabilityStepBase):
    def test_unresolved_dependency_refuses_execution_before_any_handler_lookup(self):
        blocker = self.plans.add_step(self.plan.plan_id, "Blocker step")
        step = self.plans.add_step(
            self.plan.plan_id, "Dependent step",
            dependencies=[blocker.step_id], required_capabilities=["send_email"],
        )
        self.plans.update_step_status(self.plan.plan_id, step.step_id, STATUS_READY)
        calls = []
        self.engine.capability_handlers.register(
            "send_email", lambda plan_step: calls.append("send_email")
        )

        result = self.engine.execute_capability_step(self.plan.plan_id, step.step_id)

        self.assertEqual(result.status, EXEC_STATUS_FAILED)
        self.assertEqual(calls, [])

    def test_unavailable_capability_in_capability_system_refuses_execution(self):
        step = self._ready_step(required_capabilities=["send_email"])
        self.engine.capability_handlers.register("send_email", lambda plan_step: "ok")
        caps = FakeCapabilitySystem()  # nothing registered/enabled

        result = self.engine.execute_capability_step(
            self.plan.plan_id, step.step_id, capability_system=caps
        )

        self.assertEqual(result.status, EXEC_STATUS_FAILED)
        self.assertEqual(self.plans.get_step(self.plan.plan_id, step.step_id).status,
                          STATUS_READY)

    def test_non_ready_step_refuses_execution(self):
        step = self.plans.add_step(
            self.plan.plan_id, "Not ready", required_capabilities=["send_email"]
        )
        self.engine.capability_handlers.register("send_email", lambda plan_step: "ok")

        result = self.engine.execute_capability_step(self.plan.plan_id, step.step_id)

        self.assertEqual(result.status, EXEC_STATUS_FAILED)

    def test_unknown_plan_refuses_execution(self):
        result = self.engine.execute_capability_step("no-such-plan", "no-such-step")
        self.assertEqual(result.status, EXEC_STATUS_FAILED)


class TestExecutionHistoryStaysCorrect(TestExecuteCapabilityStepBase):
    def test_successful_capability_execution_is_recorded_in_history(self):
        step = self._ready_step(required_capabilities=["send_email"])
        self.engine.capability_handlers.register("send_email", lambda plan_step: "ok")

        result = self.engine.execute_capability_step(self.plan.plan_id, step.step_id)

        self.assertEqual(len(self.engine.history), 1)
        self.assertIs(self.engine.history.get(result.execution_id), result)

    def test_missing_handler_failure_is_recorded_in_history(self):
        step = self._ready_step(required_capabilities=["send_email"])

        result = self.engine.execute_capability_step(self.plan.plan_id, step.step_id)

        self.assertEqual(len(self.engine.history), 1)
        self.assertIs(self.engine.history.get(result.execution_id), result)

    def test_capability_and_ordinary_execution_share_the_same_history(self):
        step_a = self._ready_step(description="A", required_capabilities=["send_email"])
        step_b = self._ready_step(description="B")
        self.engine.capability_handlers.register("send_email", lambda plan_step: "ok")

        self.engine.execute_capability_step(self.plan.plan_id, step_a.step_id)
        self.engine.execute_step(self.plan.plan_id, step_b.step_id, lambda plan_step: "ok")

        self.assertEqual(len(self.engine.history), 2)
        self.assertEqual(
            [r.step_id for r in self.engine.history.list_for_plan(self.plan.plan_id)],
            [step_a.step_id, step_b.step_id],
        )


class TestConstructionWithCapabilityHandlers(unittest.TestCase):
    def test_accepts_an_explicit_registry(self):
        goals = GoalManager()
        plans = PlanManager(goals)
        registry = CapabilityHandlerRegistry()
        engine = ExecutionEngine(plans, capability_handlers=registry)
        self.assertIs(engine.capability_handlers, registry)

    def test_rejects_a_non_registry_capability_handlers_argument(self):
        goals = GoalManager()
        plans = PlanManager(goals)
        with self.assertRaises(TypeError):
            ExecutionEngine(plans, capability_handlers="not-a-registry")

    def test_defaults_to_a_private_empty_registry(self):
        goals = GoalManager()
        plans = PlanManager(goals)
        engine = ExecutionEngine(plans)
        self.assertIsInstance(engine.capability_handlers, CapabilityHandlerRegistry)
        self.assertEqual(engine.capability_handlers.list_registered(), [])


class _FakeStep:
    """Minimal stand-in for a PlanStep (planning/plan.py) - exposes
    only the `required_capabilities` attribute
    `check_execution_readiness` actually reads, for tests that want to
    exercise the registry in isolation without a full
    GoalManager/PlanManager/PlanStep chain."""

    def __init__(self, required_capabilities):
        self.required_capabilities = list(required_capabilities)


# ----------------------------------------------------------------------
# CapabilityHandlerRegistry.check_execution_readiness on its own
# ----------------------------------------------------------------------
class TestReadinessCapabilityAvailableHandlerRegistered(unittest.TestCase):
    def test_single_ready_capability_reports_ready_true(self):
        registry = CapabilityHandlerRegistry()
        registry.register("send_email", lambda step: "ok")
        caps = FakeCapabilitySystem(registered={"send_email": True})
        step = _FakeStep(["send_email"])

        result = registry.check_execution_readiness(step, caps)

        self.assertIsInstance(result, CapabilityReadinessResult)
        self.assertTrue(result.ready)
        self.assertEqual(result.missing_capabilities, [])
        self.assertEqual(result.unavailable_capabilities, [])
        self.assertEqual(result.missing_handlers, [])
        self.assertEqual(result.capabilities, [{
            "capability_name": "send_email",
            "available": True,
            "handler_registered": True,
            "status": "ready",
        }])


class TestReadinessCapabilityUnavailable(unittest.TestCase):
    def test_disabled_capability_is_reported_unavailable_and_not_ready(self):
        registry = CapabilityHandlerRegistry()
        registry.register("send_email", lambda step: "ok")
        caps = FakeCapabilitySystem(registered={"send_email": False})
        step = _FakeStep(["send_email"])

        result = registry.check_execution_readiness(step, caps)

        self.assertFalse(result.ready)
        self.assertEqual(result.unavailable_capabilities, ["send_email"])
        self.assertEqual(result.missing_capabilities, [])
        self.assertEqual(result.missing_handlers, [])
        entry = result.capabilities[0]
        self.assertFalse(entry["available"])
        self.assertTrue(entry["handler_registered"])
        self.assertEqual(entry["status"], "unavailable")


class TestReadinessCapabilityRegisteredHandlerMissing(unittest.TestCase):
    def test_available_capability_without_a_handler_is_reported_missing_handler(self):
        registry = CapabilityHandlerRegistry()
        caps = FakeCapabilitySystem(registered={"send_email": True})
        step = _FakeStep(["send_email"])

        result = registry.check_execution_readiness(step, caps)

        self.assertFalse(result.ready)
        self.assertEqual(result.missing_handlers, ["send_email"])
        self.assertEqual(result.missing_capabilities, [])
        self.assertEqual(result.unavailable_capabilities, [])
        entry = result.capabilities[0]
        self.assertTrue(entry["available"])
        self.assertFalse(entry["handler_registered"])
        self.assertEqual(entry["status"], "missing_handler")


class TestReadinessMissingCapability(unittest.TestCase):
    def test_capability_not_in_the_registry_is_reported_missing(self):
        registry = CapabilityHandlerRegistry()
        registry.register("send_email", lambda step: "ok")
        caps = FakeCapabilitySystem()  # nothing registered at all
        step = _FakeStep(["send_email"])

        result = registry.check_execution_readiness(step, caps)

        self.assertFalse(result.ready)
        self.assertEqual(result.missing_capabilities, ["send_email"])
        self.assertEqual(result.unavailable_capabilities, [])
        entry = result.capabilities[0]
        self.assertFalse(entry["available"])
        self.assertEqual(entry["status"], "missing_capability")

    def test_missing_capability_with_no_handler_appears_in_both_lists(self):
        registry = CapabilityHandlerRegistry()
        caps = FakeCapabilitySystem()  # nothing registered
        step = _FakeStep(["send_email"])

        result = registry.check_execution_readiness(step, caps)

        self.assertEqual(result.missing_capabilities, ["send_email"])
        self.assertEqual(result.missing_handlers, ["send_email"])
        # The more fundamental problem wins for the single `status`.
        self.assertEqual(result.capabilities[0]["status"], "missing_capability")


class TestReadinessMultipleCapabilities(unittest.TestCase):
    def test_reports_one_entry_per_required_capability_in_order(self):
        registry = CapabilityHandlerRegistry()
        registry.register("send_email", lambda step: "ok")
        registry.register("send_sms", lambda step: "ok")
        caps = FakeCapabilitySystem(registered={"send_email": True, "send_sms": True})
        step = _FakeStep(["send_email", "send_sms"])

        result = registry.check_execution_readiness(step, caps)

        self.assertTrue(result.ready)
        self.assertEqual(
            [entry["capability_name"] for entry in result.capabilities],
            ["send_email", "send_sms"],
        )


class TestReadinessMixedReadyAndUnready(unittest.TestCase):
    def test_mix_of_problems_across_capabilities_is_reported_independently(self):
        registry = CapabilityHandlerRegistry()
        registry.register("send_email", lambda step: "ok")   # ready
        registry.register("send_sms", lambda step: "ok")     # capability disabled
        # "send_push" - no handler registered
        # "unknown_cap" - not in the capability registry at all
        caps = FakeCapabilitySystem(registered={
            "send_email": True, "send_sms": False, "send_push": True,
        })
        step = _FakeStep(["send_email", "send_sms", "send_push", "unknown_cap"])

        result = registry.check_execution_readiness(step, caps)

        self.assertFalse(result.ready)
        self.assertEqual(result.unavailable_capabilities, ["send_sms"])
        self.assertEqual(result.missing_handlers, ["send_push", "unknown_cap"])
        self.assertEqual(result.missing_capabilities, ["unknown_cap"])

        statuses = {e["capability_name"]: e["status"] for e in result.capabilities}
        self.assertEqual(statuses["send_email"], "ready")
        self.assertEqual(statuses["send_sms"], "unavailable")
        self.assertEqual(statuses["send_push"], "missing_handler")
        self.assertEqual(statuses["unknown_cap"], "missing_capability")

    def test_empty_required_capabilities_is_trivially_ready(self):
        registry = CapabilityHandlerRegistry()
        step = _FakeStep([])

        result = registry.check_execution_readiness(step, FakeCapabilitySystem())

        self.assertTrue(result.ready)
        self.assertEqual(result.capabilities, [])
        self.assertEqual(result.warnings, [])

    def test_omitted_capability_system_skips_availability_and_warns(self):
        registry = CapabilityHandlerRegistry()
        registry.register("send_email", lambda step: "ok")
        step = _FakeStep(["send_email"])

        result = registry.check_execution_readiness(step)

        self.assertTrue(result.ready)
        self.assertEqual(result.missing_capabilities, [])
        self.assertEqual(result.unavailable_capabilities, [])
        self.assertTrue(result.warnings)


class TestReadinessNeverExecutesAHandler(unittest.TestCase):
    def test_check_execution_readiness_never_calls_any_handler(self):
        registry = CapabilityHandlerRegistry()
        calls = []
        registry.register("send_email", lambda step: calls.append("send_email"))
        registry.register("send_sms", lambda step: calls.append("send_sms"))
        caps = FakeCapabilitySystem(registered={"send_email": True, "send_sms": True})
        step = _FakeStep(["send_email", "send_sms"])

        registry.check_execution_readiness(step, caps)

        self.assertEqual(calls, [])

    def test_readiness_check_never_registers_or_changes_a_handler(self):
        registry = CapabilityHandlerRegistry()
        caps = FakeCapabilitySystem(registered={"send_email": True})
        step = _FakeStep(["send_email"])

        registry.check_execution_readiness(step, caps)

        self.assertEqual(registry.list_registered(), [])


# ----------------------------------------------------------------------
# ExecutionEngine.execute_capability_step using the readiness check
# ----------------------------------------------------------------------
class TestExecuteCapabilityStepRefusesUnreadyStep(TestExecuteCapabilityStepBase):
    def test_unavailable_capability_refuses_with_no_handler_call(self):
        step = self._ready_step(required_capabilities=["send_email"])
        calls = []
        self.engine.capability_handlers.register(
            "send_email", lambda plan_step: calls.append("send_email")
        )
        caps = FakeCapabilitySystem(registered={"send_email": False})

        result = self.engine.execute_capability_step(
            self.plan.plan_id, step.step_id, capability_system=caps
        )

        self.assertEqual(result.status, EXEC_STATUS_FAILED)
        self.assertEqual(calls, [])
        self.assertEqual(
            self.plans.get_step(self.plan.plan_id, step.step_id).status, STATUS_READY
        )

    def test_readiness_failure_is_recorded_with_structured_detail(self):
        step = self._ready_step(required_capabilities=["send_email"])
        # Available in capability_system (so preflight itself passes),
        # but no handler registered - only the readiness check catches
        # this, since preflight never knows about the handler registry.
        caps = FakeCapabilitySystem(registered={"send_email": True})

        result = self.engine.execute_capability_step(
            self.plan.plan_id, step.step_id, capability_system=caps
        )

        self.assertEqual(result.status, EXEC_STATUS_FAILED)
        self.assertIn("send_email", result.error)
        self.assertIn("readiness", result.metadata)
        self.assertFalse(result.metadata["readiness"]["ready"])
        self.assertEqual(self.engine.history.get(result.execution_id), result)

    def test_a_ready_capability_never_runs_alongside_an_unready_one(self):
        step = self._ready_step(
            required_capabilities=["send_email", "send_sms"]
        )
        calls = []
        self.engine.capability_handlers.register(
            "send_email", lambda plan_step: calls.append("send_email")
        )
        # "send_sms" has no registered handler at all.
        caps = FakeCapabilitySystem(registered={"send_email": True, "send_sms": True})

        result = self.engine.execute_capability_step(
            self.plan.plan_id, step.step_id, capability_system=caps
        )

        self.assertEqual(result.status, EXEC_STATUS_FAILED)
        self.assertEqual(calls, [])


class TestExistingSuccessfulExecutionStillWorks(TestExecuteCapabilityStepBase):
    def test_ready_step_with_available_capabilities_still_completes(self):
        step = self._ready_step(
            required_capabilities=["send_email", "send_sms"]
        )
        self.engine.capability_handlers.register("send_email", lambda plan_step: "emailed")
        self.engine.capability_handlers.register("send_sms", lambda plan_step: "texted")
        caps = FakeCapabilitySystem(registered={"send_email": True, "send_sms": True})

        result = self.engine.execute_capability_step(
            self.plan.plan_id, step.step_id, capability_system=caps
        )

        self.assertEqual(result.status, EXEC_STATUS_COMPLETED)
        self.assertEqual(result.output, {"send_email": "emailed", "send_sms": "texted"})
        self.assertEqual(
            self.plans.get_step(self.plan.plan_id, step.step_id).status, STATUS_COMPLETED
        )

    def test_still_works_without_a_capability_system_supplied(self):
        step = self._ready_step(required_capabilities=["send_email"])
        self.engine.capability_handlers.register("send_email", lambda plan_step: "ok")

        result = self.engine.execute_capability_step(self.plan.plan_id, step.step_id)

        self.assertEqual(result.status, EXEC_STATUS_COMPLETED)
        self.assertEqual(result.output, {"send_email": "ok"})


if __name__ == "__main__":
    unittest.main()
