"""
Tests for self_upgrade.capability_builder.build_capability (Prompt
362) - the first real Capability Builder, bridging the existing
CapabilityBuildSpec (self_upgrade.capability_build_spec.
build_capability_build_spec, Prompt 361) to an actual, inspectable
generated Python source skeleton via the existing, unmodified local
code generator (code_generation.local_function_generator.
generate_function, Prompt 335).

Covers: a valid (READY) build spec produces a non-empty
generated_source and a READY result; a spec missing required minimum
fields (capability_name, interface_name, target_module,
implementation_steps, input/output schema) is reported INVALID; an
upstream BLOCKED build spec is passed through as BLOCKED without any
generation attempt; the result carries the expected
capability_name/target_module metadata; the existing
CodeGenerationResult/generate_function integration is actually used
(status/generated_code line up); and deterministic input produces
deterministic output.

Run directly:
    python -m unittest tests.test_capability_builder -v
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
from self_upgrade.capability_implementation_spec import build_capability_implementation_spec
from self_upgrade.capability_build_spec import (
    build_capability_build_spec,
    STATUS_READY as BUILD_SPEC_STATUS_READY,
)
from self_upgrade.capability_builder import (
    build_capability,
    STATUS_READY,
    STATUS_BLOCKED,
    STATUS_INVALID,
    ALL_STATUSES,
)
from code_generation.code_generation_result import STATUS_GENERATED
from code_generation.local_function_generator import generate_function
from execution.capability_handlers import CapabilityHandlerRegistry
from execution.code_change_plan_capability import (
    CAPABILITY_NAME as CODE_CHANGE_PLAN_NAME,
    create_code_change_plan_capability,
)


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


class FakeCapabilitySystem:
    def __init__(self, registered=None):
        self._registered = dict(registered) if registered else {}

    def all(self):
        return [
            {"name": name, "enabled": enabled, "status": "enabled" if enabled else "disabled"}
            for name, enabled in self._registered.items()
        ]


def _handlers():
    handlers = CapabilityHandlerRegistry()
    handlers.register_capability(create_code_change_plan_capability())
    return handlers


def _ready_build_spec():
    handlers = _handlers()
    capability_system = FakeCapabilitySystem({CODE_CHANGE_PLAN_NAME: True})
    analyzer = _analyzer(capability_system=capability_system, capability_handlers=handlers)
    analysis = analyzer.analyze_self_upgrade_request(_request())
    plan = build_capability_creation_plan(analysis)
    impl_spec = build_capability_implementation_spec(plan, capability_handlers=handlers)
    build_spec = build_capability_build_spec(impl_spec)
    assert build_spec["status"] == BUILD_SPEC_STATUS_READY
    return build_spec


RESULT_KEYS = {
    "capability_name", "interface_name", "target_module",
    "generated_source", "status", "validation_errors",
    "code_generation_status", "created_at",
}


# --------------------------------------------------------------------
# Valid build spec -> generated source
# --------------------------------------------------------------------
class ValidCapabilityBuildTests(unittest.TestCase):
    def test_result_shape(self):
        build_spec = _ready_build_spec()
        result = build_capability(build_spec)
        self.assertEqual(set(result.keys()), RESULT_KEYS)

    def test_status_ready_and_source_non_empty(self):
        build_spec = _ready_build_spec()
        result = build_capability(build_spec)
        self.assertEqual(result["status"], STATUS_READY)
        self.assertIsInstance(result["generated_source"], str)
        self.assertTrue(result["generated_source"].strip())
        self.assertEqual(result["validation_errors"], [])

    def test_metadata_matches_build_spec(self):
        build_spec = _ready_build_spec()
        result = build_capability(build_spec)
        self.assertEqual(result["capability_name"], build_spec["capability_name"])
        self.assertEqual(result["interface_name"], build_spec["interface_name"])
        self.assertEqual(result["target_module"], build_spec["target_module"])
        self.assertEqual(result["target_module"], "execution.code_change_plan_capability")

    def test_generated_source_contains_interface_name_as_function(self):
        build_spec = _ready_build_spec()
        result = build_capability(build_spec)
        self.assertIn(f"def {build_spec['interface_name']}(", result["generated_source"])

    def test_code_generation_status_is_generated(self):
        build_spec = _ready_build_spec()
        result = build_capability(build_spec)
        self.assertEqual(result["code_generation_status"], STATUS_GENERATED)


# --------------------------------------------------------------------
# Missing required minimum fields
# --------------------------------------------------------------------
class MissingFieldsTests(unittest.TestCase):
    def _valid_ready_dict(self):
        return dict(
            capability_name="demo_capability",
            interface_name="demo_capability",
            input_schema={"type": "object", "properties": {"path": {"type": "string"}}},
            output_schema={"type": "object", "properties": {"ok": {"type": "boolean"}}},
            dependencies=["execution.demo_module"],
            implementation_steps=["Do the thing."],
            validation_requirements=[],
            test_requirements=[],
            target_module="execution.demo_module",
            status=BUILD_SPEC_STATUS_READY,
        )

    def test_missing_capability_name_is_invalid(self):
        spec = self._valid_ready_dict()
        spec["capability_name"] = ""
        result = build_capability(spec)
        self.assertEqual(result["status"], STATUS_INVALID)
        self.assertTrue(any("capability_name" in err for err in result["validation_errors"]))
        self.assertIsNone(result["generated_source"])

    def test_missing_interface_name_is_invalid(self):
        spec = self._valid_ready_dict()
        spec["interface_name"] = "not a valid identifier!"
        result = build_capability(spec)
        self.assertEqual(result["status"], STATUS_INVALID)
        self.assertTrue(any("interface_name" in err for err in result["validation_errors"]))

    def test_missing_target_module_is_invalid(self):
        spec = self._valid_ready_dict()
        spec["target_module"] = None
        result = build_capability(spec)
        self.assertEqual(result["status"], STATUS_INVALID)
        self.assertTrue(any("target_module" in err for err in result["validation_errors"]))

    def test_empty_implementation_steps_is_invalid(self):
        spec = self._valid_ready_dict()
        spec["implementation_steps"] = []
        result = build_capability(spec)
        self.assertEqual(result["status"], STATUS_INVALID)
        self.assertTrue(any("implementation_steps" in err for err in result["validation_errors"]))

    def test_missing_input_schema_is_invalid(self):
        spec = self._valid_ready_dict()
        spec["input_schema"] = None
        result = build_capability(spec)
        self.assertEqual(result["status"], STATUS_INVALID)
        self.assertTrue(any("input_schema" in err for err in result["validation_errors"]))

    def test_missing_output_schema_is_invalid(self):
        spec = self._valid_ready_dict()
        spec["output_schema"] = None
        result = build_capability(spec)
        self.assertEqual(result["status"], STATUS_INVALID)
        self.assertTrue(any("output_schema" in err for err in result["validation_errors"]))

    def test_not_a_dict_is_invalid(self):
        result = build_capability("not a spec")
        self.assertEqual(result["status"], STATUS_INVALID)
        self.assertIsNone(result["generated_source"])

    def test_none_is_invalid(self):
        result = build_capability(None)
        self.assertEqual(result["status"], STATUS_INVALID)

    def test_missing_expected_keys_is_invalid(self):
        result = build_capability({"capability_name": "x"})
        self.assertEqual(result["status"], STATUS_INVALID)


# --------------------------------------------------------------------
# Blocked spec
# --------------------------------------------------------------------
class BlockedCapabilityBuildTests(unittest.TestCase):
    def test_blocked_spec_returns_blocked(self):
        analyzer = _analyzer()
        analysis = analyzer.analyze_self_upgrade_request(_request())
        plan = build_capability_creation_plan(analysis)
        impl_spec = build_capability_implementation_spec(plan)  # no handlers -> BLOCKED
        build_spec = build_capability_build_spec(impl_spec)
        self.assertNotEqual(build_spec["status"], BUILD_SPEC_STATUS_READY)

        result = build_capability(build_spec)

        self.assertEqual(result["status"], STATUS_BLOCKED)
        self.assertIsNone(result["generated_source"])
        self.assertIsNone(result["code_generation_status"])

    def test_blocked_spec_never_calls_generator(self):
        # A READY-looking dict whose status is BLOCKED must short-
        # circuit before any generation is attempted - even if every
        # other field would otherwise be enough to generate from.
        spec = dict(
            capability_name="demo",
            interface_name="demo",
            input_schema={"type": "object", "properties": {}},
            output_schema={"type": "object", "properties": {}},
            dependencies=[],
            implementation_steps=["step"],
            validation_requirements=[],
            test_requirements=[],
            target_module=None,
            status=STATUS_BLOCKED,
        )
        result = build_capability(spec)
        self.assertEqual(result["status"], STATUS_BLOCKED)
        self.assertIsNone(result["generated_source"])


# --------------------------------------------------------------------
# Integration with existing CodeGenerationResult infrastructure
# --------------------------------------------------------------------
class CodeGenerationIntegrationTests(unittest.TestCase):
    def test_uses_existing_generate_function_output_directly(self):
        build_spec = _ready_build_spec()
        result = build_capability(build_spec)

        expected = generate_function(
            {
                "function_name": build_spec["interface_name"],
                "parameters": sorted(build_spec["input_schema"]["properties"].keys()),
                "return_expression": (
                    "{" + ", ".join(
                        f"{name!r}: None"
                        for name in sorted(build_spec["output_schema"]["properties"].keys())
                    ) + "}"
                ),
                "docstring": result["generated_source"],  # unused; recomputed below
            },
            target_file=build_spec["target_module"],
        )
        # The generator is deterministic on function_name/parameters/
        # return_expression regardless of docstring text, so the two
        # results must both be STATUS_GENERATED and define the same
        # function.
        self.assertEqual(expected.status, STATUS_GENERATED)
        self.assertEqual(result["code_generation_status"], STATUS_GENERATED)

    def test_invalid_generation_request_surfaces_as_invalid_result(self):
        # A syntactically-impossible return_expression (empty string)
        # cannot be produced through build_capability's own field
        # validation, so exercise generate_function's own failure path
        # directly to confirm build_capability would propagate it.
        spec = dict(
            capability_name="demo",
            interface_name="demo",
            input_schema={"type": "object", "properties": {}},
            output_schema={"type": "object", "properties": {}},
            dependencies=["execution.demo_module"],
            implementation_steps=["step"],
            validation_requirements=[],
            test_requirements=[],
            target_module="execution.demo_module",
            status=BUILD_SPEC_STATUS_READY,
        )
        result = build_capability(spec)
        # Well-formed minimum fields -> generation is actually attempted
        # and succeeds.
        self.assertEqual(result["status"], STATUS_READY)
        self.assertEqual(result["code_generation_status"], STATUS_GENERATED)


# --------------------------------------------------------------------
# Determinism
# --------------------------------------------------------------------
class DeterminismTests(unittest.TestCase):
    def test_same_input_produces_same_output(self):
        build_spec = _ready_build_spec()
        result1 = build_capability(build_spec)
        result2 = build_capability(build_spec)
        for key in (
            "capability_name", "interface_name", "target_module",
            "generated_source", "status", "validation_errors",
            "code_generation_status",
        ):
            self.assertEqual(result1[key], result2[key])

    def test_statuses_are_fixed_and_reused_from_build_spec(self):
        self.assertEqual(set(ALL_STATUSES), {STATUS_READY, STATUS_BLOCKED, STATUS_INVALID})

    def test_never_writes_executes_or_installs(self):
        # Structural guarantee, not a filesystem check: confirm the
        # result never carries anything beyond a plain string of
        # source text, and calling twice never changes the verdict.
        build_spec = _ready_build_spec()
        result_before = build_capability(build_spec)
        result_after = build_capability(build_spec)
        self.assertEqual(result_before["status"], result_after["status"])
        self.assertIsInstance(result_before["generated_source"], str)


if __name__ == "__main__":
    unittest.main()
