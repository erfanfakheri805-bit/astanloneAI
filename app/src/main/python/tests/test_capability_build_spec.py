"""
Tests for self_upgrade.capability_build_spec.build_capability_build_spec
(Prompt 361) - a small adapter turning the existing
CapabilityImplementationSpec
(self_upgrade.capability_implementation_spec.
build_capability_implementation_spec, Prompt 360) into one structured
CapabilityBuildSpec.

Covers: a valid (READY) build spec with an unambiguous target_module
and real schemas/requirements carried through unchanged; a BLOCKED
build spec when the implementation spec itself is BLOCKED or when a
READY spec's dependencies don't name exactly one module; and an
INVALID build spec for a malformed/invalid implementation spec.

Run directly:
    python -m unittest tests.test_capability_build_spec -v
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
from self_upgrade.capability_creation_plan import build_capability_creation_plan
from self_upgrade.capability_implementation_spec import (
    build_capability_implementation_spec,
    STATUS_READY as IMPL_STATUS_READY,
    STATUS_BLOCKED as IMPL_STATUS_BLOCKED,
)
from self_upgrade.capability_build_spec import (
    build_capability_build_spec,
    STATUS_READY,
    STATUS_BLOCKED,
    STATUS_INVALID,
    ALL_STATUSES,
)
from execution.capability_handlers import CapabilityHandlerRegistry
from execution.code_change_plan_capability import (
    CAPABILITY_NAME as CODE_CHANGE_PLAN_NAME,
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


def _ready_impl_spec(capability_handlers):
    capability_system = FakeCapabilitySystem({CODE_CHANGE_PLAN_NAME: True})
    analyzer = _analyzer(capability_system=capability_system, capability_handlers=capability_handlers)
    analysis = analyzer.analyze_self_upgrade_request(_request())
    plan = build_capability_creation_plan(analysis)
    return build_capability_implementation_spec(plan, capability_handlers=capability_handlers)


BUILD_SPEC_KEYS = {
    "capability_name", "interface_name", "input_schema", "output_schema",
    "dependencies", "implementation_steps", "validation_requirements",
    "test_requirements", "target_module", "status", "created_at",
}


# --------------------------------------------------------------------
# Valid build specification
# --------------------------------------------------------------------
class ValidBuildSpecTests(unittest.TestCase):
    def _handlers(self):
        handlers = CapabilityHandlerRegistry()
        handlers.register_capability(create_code_change_plan_capability())
        return handlers

    def test_build_spec_shape(self):
        handlers = self._handlers()
        impl_spec = _ready_impl_spec(handlers)
        build_spec = build_capability_build_spec(impl_spec)
        self.assertEqual(set(build_spec.keys()), BUILD_SPEC_KEYS)

    def test_status_ready(self):
        handlers = self._handlers()
        impl_spec = _ready_impl_spec(handlers)
        self.assertEqual(impl_spec["status"], IMPL_STATUS_READY)
        build_spec = build_capability_build_spec(impl_spec)
        self.assertEqual(build_spec["status"], STATUS_READY)

    def test_fields_reused_unchanged_from_implementation_spec(self):
        handlers = self._handlers()
        impl_spec = _ready_impl_spec(handlers)
        build_spec = build_capability_build_spec(impl_spec)
        self.assertEqual(build_spec["capability_name"], impl_spec["capability_name"])
        self.assertEqual(build_spec["interface_name"], impl_spec["interface_name"])
        self.assertEqual(build_spec["input_schema"], impl_spec["inputs"])
        self.assertEqual(build_spec["output_schema"], impl_spec["outputs"])
        self.assertEqual(build_spec["dependencies"], impl_spec["dependencies"])
        self.assertEqual(build_spec["implementation_steps"], impl_spec["implementation_steps"])
        self.assertEqual(build_spec["validation_requirements"], impl_spec["validation_requirements"])
        self.assertEqual(build_spec["test_requirements"], impl_spec["test_requirements"])

    def test_target_module_is_the_single_dependency(self):
        handlers = self._handlers()
        impl_spec = _ready_impl_spec(handlers)
        self.assertEqual(len(impl_spec["dependencies"]), 1)
        build_spec = build_capability_build_spec(impl_spec)
        self.assertEqual(build_spec["target_module"], impl_spec["dependencies"][0])
        self.assertEqual(build_spec["target_module"], "execution.code_change_plan_capability")

    def test_is_json_serializable(self):
        import json
        handlers = self._handlers()
        impl_spec = _ready_impl_spec(handlers)
        build_spec = build_capability_build_spec(impl_spec)
        serialized = json.dumps(build_spec)
        self.assertIsInstance(serialized, str)

    def test_deterministic(self):
        handlers = self._handlers()
        impl_spec = _ready_impl_spec(handlers)
        build_spec1 = build_capability_build_spec(impl_spec)
        build_spec2 = build_capability_build_spec(impl_spec)
        for key in ("capability_name", "interface_name", "input_schema",
                    "output_schema", "dependencies", "implementation_steps",
                    "validation_requirements", "test_requirements",
                    "target_module", "status"):
            self.assertEqual(build_spec1[key], build_spec2[key])


# --------------------------------------------------------------------
# Blocked specification
# --------------------------------------------------------------------
class BlockedBuildSpecTests(unittest.TestCase):
    def test_blocked_when_implementation_spec_itself_is_blocked(self):
        # No capability_handlers supplied to the implementation-spec
        # step - it comes back BLOCKED (Prompt 360).
        analyzer = _analyzer()
        analysis = analyzer.analyze_self_upgrade_request(_request())
        plan = build_capability_creation_plan(analysis)
        impl_spec = build_capability_implementation_spec(plan)
        self.assertEqual(impl_spec["status"], IMPL_STATUS_BLOCKED)

        build_spec = build_capability_build_spec(impl_spec)

        self.assertEqual(build_spec["status"], STATUS_BLOCKED)
        self.assertIsNone(build_spec["target_module"])
        self.assertIsNone(build_spec["input_schema"])
        self.assertIsNone(build_spec["output_schema"])
        self.assertEqual(build_spec["implementation_steps"], [])

    def test_blocked_when_dependencies_has_zero_modules(self):
        handlers = CapabilityHandlerRegistry()
        handlers.register_capability(create_code_change_plan_capability())
        impl_spec = _ready_impl_spec(handlers)
        impl_spec = dict(impl_spec)
        impl_spec["dependencies"] = []  # simulate an ambiguous/empty case

        build_spec = build_capability_build_spec(impl_spec)

        self.assertEqual(build_spec["status"], STATUS_BLOCKED)
        self.assertIsNone(build_spec["target_module"])

    def test_blocked_when_dependencies_has_multiple_modules(self):
        handlers = CapabilityHandlerRegistry()
        handlers.register_capability(create_code_change_plan_capability())
        impl_spec = _ready_impl_spec(handlers)
        impl_spec = dict(impl_spec)
        impl_spec["dependencies"] = ["execution.module_a", "execution.module_b"]

        build_spec = build_capability_build_spec(impl_spec)

        self.assertEqual(build_spec["status"], STATUS_BLOCKED)
        self.assertIsNone(build_spec["target_module"])

    def test_blocked_spec_never_guesses_target_module(self):
        analyzer = _analyzer()
        analysis = analyzer.analyze_self_upgrade_request(_request())
        plan = build_capability_creation_plan(analysis)
        impl_spec = build_capability_implementation_spec(plan)
        build_spec = build_capability_build_spec(impl_spec)
        self.assertIsNone(build_spec["target_module"])


# --------------------------------------------------------------------
# Invalid implementation specification
# --------------------------------------------------------------------
class InvalidBuildSpecTests(unittest.TestCase):
    def test_invalid_when_implementation_spec_status_is_invalid(self):
        analyzer = _analyzer()
        analysis = analyzer.analyze_self_upgrade_request(_request(goal=""))
        plan = build_capability_creation_plan(analysis)
        impl_spec = build_capability_implementation_spec(plan)

        build_spec = build_capability_build_spec(impl_spec)

        self.assertEqual(build_spec["status"], STATUS_INVALID)
        self.assertEqual(build_spec["implementation_steps"], [])
        self.assertEqual(build_spec["validation_requirements"], [])
        self.assertEqual(build_spec["test_requirements"], [])
        self.assertIsNone(build_spec["target_module"])

    def test_invalid_when_spec_is_not_a_dict(self):
        build_spec = build_capability_build_spec("not a spec")
        self.assertEqual(build_spec["status"], STATUS_INVALID)
        self.assertIsNone(build_spec["capability_name"])
        self.assertIsNone(build_spec["target_module"])

    def test_invalid_when_spec_is_none(self):
        build_spec = build_capability_build_spec(None)
        self.assertEqual(build_spec["status"], STATUS_INVALID)

    def test_invalid_when_spec_missing_expected_keys(self):
        build_spec = build_capability_build_spec({"capability_name": "x"})
        self.assertEqual(build_spec["status"], STATUS_INVALID)

    def test_statuses_are_fixed(self):
        self.assertEqual(set(ALL_STATUSES), {STATUS_READY, STATUS_BLOCKED, STATUS_INVALID})

    def test_never_executes_or_installs_anything(self):
        handlers = CapabilityHandlerRegistry()
        handlers.register_capability(create_code_change_plan_capability())
        impl_spec = _ready_impl_spec(handlers)
        build_spec_before = build_capability_build_spec(impl_spec)
        build_spec_after = build_capability_build_spec(impl_spec)
        self.assertEqual(build_spec_before["status"], build_spec_after["status"])


if __name__ == "__main__":
    unittest.main()
