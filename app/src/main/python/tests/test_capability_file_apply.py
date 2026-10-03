"""
Tests for self_upgrade.capability_file_apply.apply_capability (Prompt
364) - the controlled, real-file-touching stage after the validated
CapabilityApplyRequest boundary (self_upgrade.
capability_apply_request.build_capability_apply_request, Prompt 363).

Every test that actually writes uses an isolated `tempfile.
TemporaryDirectory()` as `output_root`/`allowed_dirs` - never the real
project source tree - so this suite can never modify an actual project
file (requirement 11).

Covers: a valid, READY apply request creates the expected file under
the sandbox root; an INVALID apply request never writes anything; a
BLOCKED apply request never writes anything; a request whose generated
source was never actually validated (or failed validation) cannot be
applied; an already-existing file is never silently overwritten
(BLOCKED, not FAILED) when `overwrite` is not explicitly requested; a
successful result carries correct file_path/bytes_written metadata;
and the existing self-upgrade chain (through CapabilityApplyRequest)
still behaves exactly as before.

Run directly:
    python -m unittest tests.test_capability_file_apply -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from planning.goal_manager import GoalManager
from planning.plan_manager import PlanManager
from planning.adaptive_plan_analyzer import AdaptivePlanAnalyzer
from self_upgrade.self_upgrade_request import SelfUpgradeRequest
from self_upgrade.capability_creation_plan import build_capability_creation_plan
from self_upgrade.capability_implementation_spec import build_capability_implementation_spec
from self_upgrade.capability_build_spec import build_capability_build_spec
from self_upgrade.capability_builder import build_capability
from self_upgrade.capability_apply_request import (
    build_capability_apply_request,
    STATUS_READY as REQUEST_STATUS_READY,
    STATUS_BLOCKED as REQUEST_STATUS_BLOCKED,
    STATUS_INVALID as REQUEST_STATUS_INVALID,
)
from self_upgrade.capability_file_apply import (
    apply_capability,
    STATUS_APPLIED,
    STATUS_INVALID,
    STATUS_BLOCKED,
    STATUS_FAILED,
    ALL_STATUSES,
)
from code_generation.generated_code_validator import VALIDATION_VALID, VALIDATION_INVALID
from execution.capability_handlers import CapabilityHandlerRegistry
from execution.code_change_plan_capability import (
    CAPABILITY_NAME as CODE_CHANGE_PLAN_NAME,
    create_code_change_plan_capability,
)


def _self_upgrade_request(**overrides):
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


def _ready_apply_request():
    handlers = _handlers()
    capability_system = FakeCapabilitySystem({CODE_CHANGE_PLAN_NAME: True})
    analyzer = _analyzer(capability_system=capability_system, capability_handlers=handlers)
    analysis = analyzer.analyze_self_upgrade_request(_self_upgrade_request())
    plan = build_capability_creation_plan(analysis)
    impl_spec = build_capability_implementation_spec(plan, capability_handlers=handlers)
    build_spec = build_capability_build_spec(impl_spec)
    builder_result = build_capability(build_spec)
    apply_request = build_capability_apply_request(builder_result)
    assert apply_request["status"] == REQUEST_STATUS_READY
    return apply_request


def _blocked_apply_request():
    analyzer = _analyzer()
    analysis = analyzer.analyze_self_upgrade_request(_self_upgrade_request())
    plan = build_capability_creation_plan(analysis)
    impl_spec = build_capability_implementation_spec(plan)  # no handlers -> BLOCKED
    build_spec = build_capability_build_spec(impl_spec)
    builder_result = build_capability(build_spec)
    apply_request = build_capability_apply_request(builder_result)
    assert apply_request["status"] == REQUEST_STATUS_BLOCKED
    return apply_request


def _valid_ready_dict(**overrides):
    fields = dict(
        capability_name="demo_capability",
        interface_name="demo_capability",
        target_module="generated.demo_capability",
        generated_source="def demo_capability():\n    return None\n",
        status=REQUEST_STATUS_READY,
        validation_errors=[],
        validation_result={
            "status": VALIDATION_VALID,
            "error": None,
            "target_file": "generated.demo_capability",
            "generated_code": "def demo_capability():\n    return None\n",
            "analysis": {"valid": True, "syntax_error": None},
        },
        created_at="2026-01-01T00:00:00+00:00",
    )
    fields.update(overrides)
    return fields


RESULT_KEYS = {
    "capability_name", "target_module", "status", "file_path",
    "bytes_written", "validation_result", "error",
}


# --------------------------------------------------------------------
# Valid request creates the expected file
# --------------------------------------------------------------------
class ValidApplyTests(unittest.TestCase):
    def test_creates_expected_file_and_status_applied(self):
        request = _ready_apply_request()
        with tempfile.TemporaryDirectory() as sandbox:
            result = apply_capability(request, output_root=sandbox)
            self.assertEqual(result["status"], STATUS_APPLIED)
            expected_path = os.path.join(
                sandbox, request["target_module"].replace(".", os.sep) + ".py"
            )
            self.assertEqual(os.path.realpath(result["file_path"]), os.path.realpath(expected_path))
            self.assertTrue(os.path.exists(expected_path))
            with open(expected_path, "r", encoding="utf-8") as handle:
                self.assertEqual(handle.read(), request["generated_source"])

    def test_result_shape(self):
        request = _ready_apply_request()
        with tempfile.TemporaryDirectory() as sandbox:
            result = apply_capability(request, output_root=sandbox)
            self.assertEqual(set(result.keys()), RESULT_KEYS)

    def test_metadata_correct(self):
        request = _ready_apply_request()
        with tempfile.TemporaryDirectory() as sandbox:
            result = apply_capability(request, output_root=sandbox)
            self.assertEqual(result["capability_name"], request["capability_name"])
            self.assertEqual(result["target_module"], request["target_module"])
            self.assertEqual(result["bytes_written"], len(request["generated_source"].encode("utf-8")))
            self.assertEqual(result["validation_result"], request["validation_result"])
            self.assertIsNone(result["error"])


# --------------------------------------------------------------------
# INVALID request never writes
# --------------------------------------------------------------------
class InvalidRequestTests(unittest.TestCase):
    def test_invalid_request_status_never_writes(self):
        request = _valid_ready_dict(status=REQUEST_STATUS_INVALID)
        with tempfile.TemporaryDirectory() as sandbox:
            result = apply_capability(request, output_root=sandbox)
            self.assertEqual(result["status"], STATUS_INVALID)
            self.assertIsNone(result["file_path"])
            self.assertEqual(os.listdir(sandbox), [])

    def test_not_a_dict_is_invalid(self):
        with tempfile.TemporaryDirectory() as sandbox:
            result = apply_capability("not a request", output_root=sandbox)
            self.assertEqual(result["status"], STATUS_INVALID)
            self.assertEqual(os.listdir(sandbox), [])

    def test_missing_expected_keys_is_invalid(self):
        with tempfile.TemporaryDirectory() as sandbox:
            result = apply_capability({"capability_name": "x"}, output_root=sandbox)
            self.assertEqual(result["status"], STATUS_INVALID)


# --------------------------------------------------------------------
# BLOCKED path never writes
# --------------------------------------------------------------------
class BlockedRequestTests(unittest.TestCase):
    def test_blocked_upstream_request_never_writes(self):
        request = _blocked_apply_request()
        with tempfile.TemporaryDirectory() as sandbox:
            result = apply_capability(request, output_root=sandbox)
            self.assertEqual(result["status"], STATUS_BLOCKED)
            self.assertIsNone(result["file_path"])
            self.assertEqual(os.listdir(sandbox), [])

    def test_target_outside_allowed_dirs_is_blocked_not_failed(self):
        request = _ready_apply_request()
        with tempfile.TemporaryDirectory() as sandbox, \
                tempfile.TemporaryDirectory() as other_dir:
            result = apply_capability(
                request, output_root=sandbox, allowed_dirs=[other_dir],
            )
            self.assertEqual(result["status"], STATUS_BLOCKED)
            self.assertIsNone(result["file_path"])
            self.assertEqual(os.listdir(sandbox), [])


# --------------------------------------------------------------------
# Invalid generated source cannot be applied
# --------------------------------------------------------------------
class UnvalidatedSourceTests(unittest.TestCase):
    def test_missing_validation_result_is_invalid(self):
        request = _valid_ready_dict(validation_result=None)
        with tempfile.TemporaryDirectory() as sandbox:
            result = apply_capability(request, output_root=sandbox)
            self.assertEqual(result["status"], STATUS_INVALID)
            self.assertEqual(os.listdir(sandbox), [])

    def test_failed_validation_result_is_invalid(self):
        request = _valid_ready_dict(
            validation_result={
                "status": VALIDATION_INVALID,
                "error": "Generated code failed to parse: bad syntax",
                "target_file": "generated.demo_capability",
                "generated_code": "def demo_capability(:\n",
                "analysis": None,
            }
        )
        with tempfile.TemporaryDirectory() as sandbox:
            result = apply_capability(request, output_root=sandbox)
            self.assertEqual(result["status"], STATUS_INVALID)
            self.assertEqual(os.listdir(sandbox), [])

    def test_empty_generated_source_is_invalid(self):
        request = _valid_ready_dict(generated_source="")
        with tempfile.TemporaryDirectory() as sandbox:
            result = apply_capability(request, output_root=sandbox)
            self.assertEqual(result["status"], STATUS_INVALID)


# --------------------------------------------------------------------
# Protected/existing file is not overwritten when prohibited
# --------------------------------------------------------------------
class ProtectedExistingFileTests(unittest.TestCase):
    def test_existing_file_blocked_without_overwrite(self):
        request = _ready_apply_request()
        with tempfile.TemporaryDirectory() as sandbox:
            expected_path = os.path.join(
                sandbox, request["target_module"].replace(".", os.sep) + ".py"
            )
            os.makedirs(os.path.dirname(expected_path), exist_ok=True)
            with open(expected_path, "w", encoding="utf-8") as handle:
                handle.write("# pre-existing protected content\n")

            result = apply_capability(request, output_root=sandbox)

            self.assertEqual(result["status"], STATUS_BLOCKED)
            self.assertIsNone(result["file_path"])
            with open(expected_path, "r", encoding="utf-8") as handle:
                self.assertEqual(handle.read(), "# pre-existing protected content\n")

    def test_existing_file_applied_when_overwrite_explicit(self):
        request = _ready_apply_request()
        with tempfile.TemporaryDirectory() as sandbox:
            expected_path = os.path.join(
                sandbox, request["target_module"].replace(".", os.sep) + ".py"
            )
            os.makedirs(os.path.dirname(expected_path), exist_ok=True)
            with open(expected_path, "w", encoding="utf-8") as handle:
                handle.write("# old content\n")

            result = apply_capability(request, output_root=sandbox, overwrite=True)

            self.assertEqual(result["status"], STATUS_APPLIED)
            with open(expected_path, "r", encoding="utf-8") as handle:
                self.assertEqual(handle.read(), request["generated_source"])


# --------------------------------------------------------------------
# Existing project behavior remains unchanged
# --------------------------------------------------------------------
class ExistingBehaviorUnchangedTests(unittest.TestCase):
    def test_apply_request_chain_still_behaves_as_before(self):
        request = _ready_apply_request()
        self.assertEqual(request["status"], REQUEST_STATUS_READY)
        self.assertEqual(request["validation_result"]["status"], VALIDATION_VALID)

    def test_statuses_are_fixed(self):
        self.assertEqual(
            set(ALL_STATUSES), {STATUS_APPLIED, STATUS_INVALID, STATUS_BLOCKED, STATUS_FAILED}
        )

    def test_does_not_mutate_request(self):
        request = _ready_apply_request()
        before = dict(request)
        with tempfile.TemporaryDirectory() as sandbox:
            apply_capability(request, output_root=sandbox)
        self.assertEqual(request, before)

    def test_real_project_source_tree_is_never_touched(self):
        # Confirm the actual project module this request's
        # target_module maps to is never written by this stage - the
        # sandbox output_root is the only thing ever modified.
        request = _ready_apply_request()
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        real_module_path = os.path.join(
            project_root, request["target_module"].replace(".", os.sep) + ".py"
        )
        self.assertTrue(os.path.exists(real_module_path))
        before_mtime = os.path.getmtime(real_module_path)

        with tempfile.TemporaryDirectory() as sandbox:
            apply_capability(request, output_root=sandbox)

        after_mtime = os.path.getmtime(real_module_path)
        self.assertEqual(before_mtime, after_mtime)


if __name__ == "__main__":
    unittest.main()
