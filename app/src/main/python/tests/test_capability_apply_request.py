"""
Tests for self_upgrade.capability_apply_request.
build_capability_apply_request (Prompt 363) - the safe boundary
between a successful CapabilityBuilder result (self_upgrade.
capability_builder.build_capability, Prompt 362) and a future,
not-yet-built, controlled file-write stage.

Covers: a valid, READY CapabilityBuilder result becomes a READY
CapabilityApplyRequest; a missing/empty generated_source becomes
INVALID; a non-READY builder result (INVALID/BLOCKED) becomes
INVALID/BLOCKED respectively, unchanged; syntactically-invalid
generated Python is rejected as INVALID; a missing target_module is
rejected as INVALID; validate_generated_code's own validation_result
is preserved unchanged on the returned request; and this stage never
writes a file, executes code, or registers/activates anything -
existing project behavior (the rest of the self-upgrade chain) is
unaffected.

Run directly:
    python -m unittest tests.test_capability_apply_request -v
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
from self_upgrade.capability_build_spec import build_capability_build_spec
from self_upgrade.capability_builder import (
    build_capability,
    STATUS_READY as BUILDER_STATUS_READY,
    STATUS_BLOCKED as BUILDER_STATUS_BLOCKED,
)
from self_upgrade.capability_apply_request import (
    build_capability_apply_request,
    STATUS_READY,
    STATUS_BLOCKED,
    STATUS_INVALID,
    ALL_STATUSES,
)
from code_generation.generated_code_validator import VALIDATION_VALID, VALIDATION_INVALID
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


def _ready_builder_result():
    handlers = _handlers()
    capability_system = FakeCapabilitySystem({CODE_CHANGE_PLAN_NAME: True})
    analyzer = _analyzer(capability_system=capability_system, capability_handlers=handlers)
    analysis = analyzer.analyze_self_upgrade_request(_request())
    plan = build_capability_creation_plan(analysis)
    impl_spec = build_capability_implementation_spec(plan, capability_handlers=handlers)
    build_spec = build_capability_build_spec(impl_spec)
    builder_result = build_capability(build_spec)
    assert builder_result["status"] == BUILDER_STATUS_READY
    return builder_result


def _blocked_builder_result():
    analyzer = _analyzer()
    analysis = analyzer.analyze_self_upgrade_request(_request())
    plan = build_capability_creation_plan(analysis)
    impl_spec = build_capability_implementation_spec(plan)  # no handlers -> BLOCKED
    build_spec = build_capability_build_spec(impl_spec)
    builder_result = build_capability(build_spec)
    assert builder_result["status"] == BUILDER_STATUS_BLOCKED
    return builder_result


REQUEST_KEYS = {
    "capability_name", "interface_name", "target_module", "generated_source",
    "status", "validation_errors", "validation_result", "created_at",
}


# --------------------------------------------------------------------
# Valid CapabilityBuilder result -> READY apply request
# --------------------------------------------------------------------
class ValidApplyRequestTests(unittest.TestCase):
    def test_result_shape(self):
        builder_result = _ready_builder_result()
        result = build_capability_apply_request(builder_result)
        self.assertEqual(set(result.keys()), REQUEST_KEYS)

    def test_status_ready_and_no_errors(self):
        builder_result = _ready_builder_result()
        result = build_capability_apply_request(builder_result)
        self.assertEqual(result["status"], STATUS_READY)
        self.assertEqual(result["validation_errors"], [])

    def test_metadata_matches_builder_result(self):
        builder_result = _ready_builder_result()
        result = build_capability_apply_request(builder_result)
        self.assertEqual(result["capability_name"], builder_result["capability_name"])
        self.assertEqual(result["interface_name"], builder_result["interface_name"])
        self.assertEqual(result["target_module"], builder_result["target_module"])
        self.assertEqual(result["generated_source"], builder_result["generated_source"])

    def test_validation_result_preserved(self):
        builder_result = _ready_builder_result()
        result = build_capability_apply_request(builder_result)
        self.assertIsNotNone(result["validation_result"])
        self.assertEqual(result["validation_result"]["status"], VALIDATION_VALID)
        self.assertEqual(
            result["validation_result"]["generated_code"], builder_result["generated_source"]
        )
        self.assertEqual(
            result["validation_result"]["target_file"], builder_result["target_module"]
        )
        self.assertIsNotNone(result["validation_result"]["analysis"])


# --------------------------------------------------------------------
# Missing generated source
# --------------------------------------------------------------------
class MissingGeneratedSourceTests(unittest.TestCase):
    def _valid_ready_dict(self):
        return dict(
            capability_name="demo_capability",
            interface_name="demo_capability",
            target_module="execution.demo_module",
            generated_source="def demo_capability():\n    return None\n",
            status=BUILDER_STATUS_READY,
            validation_errors=[],
            code_generation_status="GENERATED",
            created_at="2026-01-01T00:00:00+00:00",
        )

    def test_empty_generated_source_is_invalid(self):
        builder_result = self._valid_ready_dict()
        builder_result["generated_source"] = ""
        result = build_capability_apply_request(builder_result)
        self.assertEqual(result["status"], STATUS_INVALID)
        self.assertTrue(any("generated_source" in err for err in result["validation_errors"]))
        self.assertIsNone(result["validation_result"])

    def test_none_generated_source_is_invalid(self):
        builder_result = self._valid_ready_dict()
        builder_result["generated_source"] = None
        result = build_capability_apply_request(builder_result)
        self.assertEqual(result["status"], STATUS_INVALID)

    def test_whitespace_only_generated_source_is_invalid(self):
        builder_result = self._valid_ready_dict()
        builder_result["generated_source"] = "   \n  "
        result = build_capability_apply_request(builder_result)
        self.assertEqual(result["status"], STATUS_INVALID)


# --------------------------------------------------------------------
# Non-READY builder result
# --------------------------------------------------------------------
class NonReadyBuilderResultTests(unittest.TestCase):
    def test_blocked_builder_result_becomes_blocked(self):
        builder_result = _blocked_builder_result()
        result = build_capability_apply_request(builder_result)
        self.assertEqual(result["status"], STATUS_BLOCKED)
        self.assertIsNone(result["validation_result"])

    def test_invalid_builder_result_becomes_invalid(self):
        builder_result = dict(
            capability_name=None, interface_name=None, target_module=None,
            generated_source=None, status="INVALID", validation_errors=["some reason"],
            code_generation_status=None, created_at="2026-01-01T00:00:00+00:00",
        )
        result = build_capability_apply_request(builder_result)
        self.assertEqual(result["status"], STATUS_INVALID)
        self.assertIsNone(result["validation_result"])

    def test_not_a_dict_is_invalid(self):
        result = build_capability_apply_request("not a result")
        self.assertEqual(result["status"], STATUS_INVALID)

    def test_none_is_invalid(self):
        result = build_capability_apply_request(None)
        self.assertEqual(result["status"], STATUS_INVALID)

    def test_missing_expected_keys_is_invalid(self):
        result = build_capability_apply_request({"capability_name": "x"})
        self.assertEqual(result["status"], STATUS_INVALID)


# --------------------------------------------------------------------
# Invalid generated Python is rejected
# --------------------------------------------------------------------
class InvalidGeneratedPythonTests(unittest.TestCase):
    def test_syntax_error_is_rejected(self):
        builder_result = dict(
            capability_name="demo_capability",
            interface_name="demo_capability",
            target_module="execution.demo_module",
            generated_source="def demo_capability(:\n    return None\n",  # broken syntax
            status=BUILDER_STATUS_READY,
            validation_errors=[],
            code_generation_status="GENERATED",
            created_at="2026-01-01T00:00:00+00:00",
        )
        result = build_capability_apply_request(builder_result)
        self.assertEqual(result["status"], STATUS_INVALID)
        self.assertIsNotNone(result["validation_result"])
        self.assertEqual(result["validation_result"]["status"], VALIDATION_INVALID)
        self.assertTrue(
            any("failed validation" in err for err in result["validation_errors"])
        )


# --------------------------------------------------------------------
# Missing target module is rejected
# --------------------------------------------------------------------
class MissingTargetModuleTests(unittest.TestCase):
    def _valid_ready_dict(self):
        return dict(
            capability_name="demo_capability",
            interface_name="demo_capability",
            target_module="execution.demo_module",
            generated_source="def demo_capability():\n    return None\n",
            status=BUILDER_STATUS_READY,
            validation_errors=[],
            code_generation_status="GENERATED",
            created_at="2026-01-01T00:00:00+00:00",
        )

    def test_none_target_module_is_invalid(self):
        builder_result = self._valid_ready_dict()
        builder_result["target_module"] = None
        result = build_capability_apply_request(builder_result)
        self.assertEqual(result["status"], STATUS_INVALID)
        self.assertTrue(any("target_module" in err for err in result["validation_errors"]))

    def test_empty_target_module_is_invalid(self):
        builder_result = self._valid_ready_dict()
        builder_result["target_module"] = "   "
        result = build_capability_apply_request(builder_result)
        self.assertEqual(result["status"], STATUS_INVALID)


# --------------------------------------------------------------------
# Existing project behavior remains unchanged
# --------------------------------------------------------------------
class ExistingBehaviorUnchangedTests(unittest.TestCase):
    def test_capability_builder_still_behaves_as_before(self):
        builder_result = _ready_builder_result()
        self.assertEqual(builder_result["status"], BUILDER_STATUS_READY)
        self.assertTrue(builder_result["generated_source"].strip())

    def test_statuses_are_fixed_and_reused_from_builder(self):
        self.assertEqual(set(ALL_STATUSES), {STATUS_READY, STATUS_BLOCKED, STATUS_INVALID})

    def test_apply_request_never_mutates_builder_result(self):
        builder_result = _ready_builder_result()
        before = dict(builder_result)
        build_capability_apply_request(builder_result)
        self.assertEqual(builder_result, before)

    def test_no_file_is_written(self):
        # target_module here is an existing real project module
        # (execution/code_change_plan_capability.py) - confirm this
        # stage never touches it: content and mtime are unchanged
        # after building the apply request.
        builder_result = _ready_builder_result()
        target_module = builder_result["target_module"]
        module_path = target_module.replace(".", "/") + ".py"
        self.assertTrue(os.path.exists(module_path))
        before_mtime = os.path.getmtime(module_path)
        with open(module_path, "r", encoding="utf-8") as handle:
            before_content = handle.read()

        build_capability_apply_request(builder_result)

        after_mtime = os.path.getmtime(module_path)
        with open(module_path, "r", encoding="utf-8") as handle:
            after_content = handle.read()
        self.assertEqual(before_mtime, after_mtime)
        self.assertEqual(before_content, after_content)


if __name__ == "__main__":
    unittest.main()
