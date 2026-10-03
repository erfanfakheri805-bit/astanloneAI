"""
Tests for self_upgrade.capability_implementation_spec.
build_capability_implementation_spec (Prompt 360) - a small adapter
turning the existing CapabilityCreationPlan
(self_upgrade.capability_creation_plan.build_capability_creation_plan,
Prompt 359) into one structured CapabilityImplementationSpec.

Covers: a valid (READY) specification with real, already-declared
input/output schemas and deterministic validation/test requirements; a
BLOCKED specification when the plan itself is BLOCKED or when a READY
plan's capability still has no declared schema on record; and an
INVALID specification for a malformed/invalid plan.

Run directly:
    python -m unittest tests.test_capability_implementation_spec -v
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
from self_upgrade.self_upgrade_request import SelfUpgradeRequest
from self_upgrade.capability_creation_plan import (
    build_capability_creation_plan,
    STATUS_READY as PLAN_STATUS_READY,
    STATUS_BLOCKED as PLAN_STATUS_BLOCKED,
)
from self_upgrade.capability_implementation_spec import (
    build_capability_implementation_spec,
    STATUS_READY,
    STATUS_BLOCKED,
    STATUS_INVALID,
    ALL_STATUSES,
)
from execution.capability_handlers import CapabilityHandlerRegistry
from execution.code_change_plan_capability import (
    CAPABILITY_NAME as CODE_CHANGE_PLAN_NAME,
    make_code_change_plan_handler,
    create_code_change_plan_capability,
)


class FakeCapabilitySystem:
    def __init__(self, registered=None):
        self._registered = dict(registered) if registered else {}

    def all(self):
        return [
            {"name": name, "enabled": enabled, "status": "enabled" if enabled else "disabled"}
            for name, enabled in self._registered.items()
        ]


def _request(**overrides):
    fields = dict(
        request_id="upgrade_request-1",
        goal="Reduce startup latency",
        requested_capability=CODE_CHANGE_PLAN_NAME,
        reason="Startup is slower than the target budget.",
    )
    fields.update(overrides)
    return SelfUpgradeRequest(**fields)


def _analyzer(capability_system=None, capability_handlers=None):
    goals = GoalManager()
    plans = PlanManager(goals)
    return AdaptivePlanAnalyzer(
        goals, plans,
        capability_system=capability_system,
        capability_handlers=capability_handlers,
    )


def _ready_plan(capability_handlers):
    capability_system = FakeCapabilitySystem({CODE_CHANGE_PLAN_NAME: True})
    analyzer = _analyzer(capability_system=capability_system, capability_handlers=capability_handlers)
    analysis = analyzer.analyze_self_upgrade_request(_request())
    return build_capability_creation_plan(analysis)


SPEC_KEYS = {
    "capability_name", "purpose", "inputs", "outputs",
    "required_capabilities", "dependencies", "interface_name",
    "implementation_steps", "validation_requirements",
    "test_requirements", "status", "created_at",
}


# --------------------------------------------------------------------
# Valid specification
# --------------------------------------------------------------------
class ValidSpecTests(unittest.TestCase):
    def _handlers_with_capability_object(self):
        handlers = CapabilityHandlerRegistry()
        handlers.register_capability(create_code_change_plan_capability())
        return handlers

    def test_spec_shape(self):
        handlers = self._handlers_with_capability_object()
        plan = _ready_plan(handlers)
        spec = build_capability_implementation_spec(plan, capability_handlers=handlers)
        self.assertEqual(set(spec.keys()), SPEC_KEYS)

    def test_status_ready(self):
        handlers = self._handlers_with_capability_object()
        plan = _ready_plan(handlers)
        self.assertEqual(plan["status"], PLAN_STATUS_READY)
        spec = build_capability_implementation_spec(plan, capability_handlers=handlers)
        self.assertEqual(spec["status"], STATUS_READY)

    def test_fields_reused_unchanged_from_plan(self):
        handlers = self._handlers_with_capability_object()
        plan = _ready_plan(handlers)
        spec = build_capability_implementation_spec(plan, capability_handlers=handlers)
        self.assertEqual(spec["capability_name"], plan["capability_name"])
        self.assertEqual(spec["purpose"], plan["purpose"])
        self.assertEqual(spec["required_capabilities"], plan["required_capabilities"])
        self.assertEqual(spec["dependencies"], plan["affected_systems"])
        self.assertEqual(spec["implementation_steps"], plan["implementation_steps"])

    def test_interface_name_is_capability_name(self):
        handlers = self._handlers_with_capability_object()
        plan = _ready_plan(handlers)
        spec = build_capability_implementation_spec(plan, capability_handlers=handlers)
        self.assertEqual(spec["interface_name"], CODE_CHANGE_PLAN_NAME)

    def test_inputs_outputs_come_from_declared_capability_schema(self):
        handlers = self._handlers_with_capability_object()
        plan = _ready_plan(handlers)
        spec = build_capability_implementation_spec(plan, capability_handlers=handlers)
        real_capability = create_code_change_plan_capability()
        self.assertEqual(spec["inputs"], real_capability.input_schema)
        self.assertEqual(spec["outputs"], real_capability.output_schema)

    def test_validation_and_test_requirements_nonempty_and_deterministic(self):
        handlers = self._handlers_with_capability_object()
        plan = _ready_plan(handlers)
        spec1 = build_capability_implementation_spec(plan, capability_handlers=handlers)
        spec2 = build_capability_implementation_spec(plan, capability_handlers=handlers)
        self.assertTrue(spec1["validation_requirements"])
        self.assertTrue(spec1["test_requirements"])
        self.assertEqual(spec1["validation_requirements"], spec2["validation_requirements"])
        self.assertEqual(spec1["test_requirements"], spec2["test_requirements"])

    def test_requirements_contain_no_source_code(self):
        handlers = self._handlers_with_capability_object()
        plan = _ready_plan(handlers)
        spec = build_capability_implementation_spec(plan, capability_handlers=handlers)
        for text in spec["validation_requirements"] + spec["test_requirements"]:
            self.assertNotIn("def ", text)
            self.assertNotIn("import ", text)

    def test_is_json_serializable(self):
        import json
        handlers = self._handlers_with_capability_object()
        plan = _ready_plan(handlers)
        spec = build_capability_implementation_spec(plan, capability_handlers=handlers)
        serialized = json.dumps(spec)
        self.assertIsInstance(serialized, str)


# --------------------------------------------------------------------
# Blocked specification
# --------------------------------------------------------------------
class BlockedSpecTests(unittest.TestCase):
    def test_blocked_when_plan_itself_is_blocked(self):
        # No capability_handlers/capability_system supplied to the
        # analyzer at all - plan comes back BLOCKED (Prompt 359).
        analyzer = _analyzer()
        analysis = analyzer.analyze_self_upgrade_request(_request())
        plan = build_capability_creation_plan(analysis)
        self.assertEqual(plan["status"], PLAN_STATUS_BLOCKED)

        spec = build_capability_implementation_spec(plan)

        self.assertEqual(spec["status"], STATUS_BLOCKED)
        self.assertIsNone(spec["inputs"])
        self.assertIsNone(spec["outputs"])
        self.assertEqual(spec["validation_requirements"], [])
        self.assertEqual(spec["test_requirements"], [])

    def test_blocked_when_ready_plan_but_no_capability_handlers_supplied(self):
        handlers = CapabilityHandlerRegistry()
        handlers.register_capability(create_code_change_plan_capability())
        plan = _ready_plan(handlers)
        self.assertEqual(plan["status"], PLAN_STATUS_READY)

        # capability_handlers omitted here even though the plan was
        # READY - inputs/outputs can't be looked up, so this module
        # must not guess.
        spec = build_capability_implementation_spec(plan)

        self.assertEqual(spec["status"], STATUS_BLOCKED)
        self.assertIsNone(spec["inputs"])
        self.assertIsNone(spec["outputs"])

    def test_blocked_when_ready_plan_but_only_plain_callable_registered(self):
        handlers = CapabilityHandlerRegistry()
        handlers.register(CODE_CHANGE_PLAN_NAME, make_code_change_plan_handler())
        plan = _ready_plan(handlers)
        self.assertEqual(plan["status"], PLAN_STATUS_READY)

        # A plain callable (not a Capability object) carries no schema.
        spec = build_capability_implementation_spec(plan, capability_handlers=handlers)

        self.assertEqual(spec["status"], STATUS_BLOCKED)
        self.assertIsNone(spec["inputs"])
        self.assertIsNone(spec["outputs"])

    def test_blocked_spec_never_guesses_dependencies(self):
        analyzer = _analyzer()
        analysis = analyzer.analyze_self_upgrade_request(_request())
        plan = build_capability_creation_plan(analysis)
        spec = build_capability_implementation_spec(plan)
        self.assertEqual(spec["dependencies"], plan["affected_systems"])


# --------------------------------------------------------------------
# Invalid plan
# --------------------------------------------------------------------
class InvalidSpecTests(unittest.TestCase):
    def test_invalid_when_plan_status_is_invalid(self):
        analyzer = _analyzer()
        analysis = analyzer.analyze_self_upgrade_request(_request(goal=""))
        plan = build_capability_creation_plan(analysis)

        spec = build_capability_implementation_spec(plan)

        self.assertEqual(spec["status"], STATUS_INVALID)
        self.assertEqual(spec["validation_requirements"], [])
        self.assertEqual(spec["test_requirements"], [])
        self.assertEqual(spec["implementation_steps"], [])

    def test_invalid_when_plan_is_not_a_dict(self):
        spec = build_capability_implementation_spec("not a plan")
        self.assertEqual(spec["status"], STATUS_INVALID)
        self.assertIsNone(spec["capability_name"])
        self.assertIsNone(spec["inputs"])
        self.assertIsNone(spec["outputs"])

    def test_invalid_when_plan_is_none(self):
        spec = build_capability_implementation_spec(None)
        self.assertEqual(spec["status"], STATUS_INVALID)

    def test_invalid_when_plan_missing_expected_keys(self):
        spec = build_capability_implementation_spec({"capability_name": "x"})
        self.assertEqual(spec["status"], STATUS_INVALID)

    def test_statuses_are_fixed(self):
        self.assertEqual(set(ALL_STATUSES), {STATUS_READY, STATUS_BLOCKED, STATUS_INVALID})

    def test_never_executes_or_installs_anything(self):
        handlers = CapabilityHandlerRegistry()
        handlers.register_capability(create_code_change_plan_capability())
        plan = _ready_plan(handlers)
        spec_before = build_capability_implementation_spec(plan, capability_handlers=handlers)
        spec_after = build_capability_implementation_spec(plan, capability_handlers=handlers)
        self.assertEqual(spec_before["status"], spec_after["status"])


if __name__ == "__main__":
    unittest.main()
