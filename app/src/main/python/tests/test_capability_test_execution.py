"""
Tests for self_upgrade.capability_test_execution.run_capability_tests
(Prompt 365) - the controlled, sandboxed test-execution stage after
controlled file application (self_upgrade.capability_file_apply.
apply_capability, Prompt 364).

Every test that actually runs the test runner uses an isolated
`tempfile.TemporaryDirectory()` as `project_dir`/`allowed_dirs` - never
the real project source tree - so this suite can never execute or
modify real project code (requirement 11).

Covers: a valid, APPLIED capability is tested and produces useful
execution metadata; a passing capability produces PASSED; a failing
capability produces FAILED; a slow capability's test correctly
produces TIMEOUT; an INVALID/malformed apply result is rejected
without execution; a BLOCKED path (upstream BLOCKED, or a file outside
the allowed workspace) is never executed; and the existing
self-upgrade chain still behaves exactly as before.

Run directly:
    python -m unittest tests.test_capability_test_execution -v
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
from self_upgrade.capability_apply_request import build_capability_apply_request
from self_upgrade.capability_file_apply import (
    apply_capability,
    STATUS_APPLIED as APPLY_STATUS_APPLIED,
    STATUS_BLOCKED as APPLY_STATUS_BLOCKED,
    STATUS_INVALID as APPLY_STATUS_INVALID,
)
from self_upgrade.capability_test_execution import (
    run_capability_tests,
    STATUS_PASSED,
    STATUS_FAILED,
    STATUS_TIMEOUT,
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


def _real_applied_result():
    """A genuine, full-chain APPLIED result - written into an isolated
    sandbox, never the real project tree."""
    handlers = _handlers()
    capability_system = FakeCapabilitySystem({CODE_CHANGE_PLAN_NAME: True})
    analyzer = _analyzer(capability_system=capability_system, capability_handlers=handlers)
    analysis = analyzer.analyze_self_upgrade_request(_self_upgrade_request())
    plan = build_capability_creation_plan(analysis)
    impl_spec = build_capability_implementation_spec(plan, capability_handlers=handlers)
    build_spec = build_capability_build_spec(impl_spec)
    builder_result = build_capability(build_spec)
    apply_request = build_capability_apply_request(builder_result)
    return apply_request


VALID_VALIDATION_RESULT = {
    "status": VALIDATION_VALID,
    "error": None,
    "target_file": "generated.demo_capability",
    "generated_code": "def demo_capability():\n    return None\n",
    "analysis": {"valid": True, "syntax_error": None},
}


def _apply_result(**overrides):
    fields = dict(
        capability_name="demo_capability",
        target_module="generated.demo_capability",
        status=APPLY_STATUS_APPLIED,
        file_path=None,  # filled in per-test, inside a sandbox
        bytes_written=42,
        validation_result=VALID_VALIDATION_RESULT,
        error=None,
    )
    fields.update(overrides)
    return fields


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


PASSING_MODULE = "def demo_capability():\n    return 42\n"
PASSING_TEST = (
    "import unittest\n"
    "from demo_capability import demo_capability\n\n"
    "class DemoCapabilityTests(unittest.TestCase):\n"
    "    def test_returns_42(self):\n"
    "        self.assertEqual(demo_capability(), 42)\n"
)
FAILING_TEST = (
    "import unittest\n"
    "from demo_capability import demo_capability\n\n"
    "class DemoCapabilityTests(unittest.TestCase):\n"
    "    def test_returns_43(self):\n"
    "        self.assertEqual(demo_capability(), 43)\n"
)
SLOW_TEST = (
    "import time\n"
    "import unittest\n\n"
    "class SlowTests(unittest.TestCase):\n"
    "    def test_sleeps_too_long(self):\n"
    "        time.sleep(5)\n"
)

RESULT_KEYS = {
    "capability_name", "file_path", "status", "tests_run", "tests_passed",
    "tests_failed", "execution_time", "output", "errors", "timeout_seconds",
}


# --------------------------------------------------------------------
# Valid applied capability is tested / PASSED
# --------------------------------------------------------------------
class PassingCapabilityTests(unittest.TestCase):
    def test_passing_capability_produces_passed(self):
        with tempfile.TemporaryDirectory() as sandbox:
            capability_path = os.path.join(sandbox, "demo_capability.py")
            _write(capability_path, PASSING_MODULE)
            _write(os.path.join(sandbox, "test_demo_capability.py"), PASSING_TEST)

            apply_result = _apply_result(file_path=capability_path)
            result = run_capability_tests(
                apply_result, project_dir=sandbox, test_target="test_demo_capability",
            )

            self.assertEqual(result["status"], STATUS_PASSED)
            self.assertEqual(result["tests_run"], 1)
            self.assertEqual(result["tests_passed"], 1)
            self.assertEqual(result["tests_failed"], 0)
            # unittest's own text runner prints its run summary to
            # stderr even on success, so `errors` (raw stderr,
            # preserved unchanged) is not necessarily empty here -
            # only that summary never reports a failure.
            self.assertFalse(any("FAILED" in err for err in result["errors"]))

    def test_result_shape_and_metadata(self):
        with tempfile.TemporaryDirectory() as sandbox:
            capability_path = os.path.join(sandbox, "demo_capability.py")
            _write(capability_path, PASSING_MODULE)
            _write(os.path.join(sandbox, "test_demo_capability.py"), PASSING_TEST)

            apply_result = _apply_result(file_path=capability_path)
            result = run_capability_tests(
                apply_result, project_dir=sandbox, test_target="test_demo_capability",
            )

            self.assertEqual(set(result.keys()), RESULT_KEYS)
            self.assertEqual(result["capability_name"], "demo_capability")
            self.assertEqual(os.path.realpath(result["file_path"]), os.path.realpath(capability_path))
            self.assertIsInstance(result["execution_time"], float)
            self.assertGreaterEqual(result["execution_time"], 0)
            self.assertIsNotNone(result["timeout_seconds"])


# --------------------------------------------------------------------
# Failing capability -> FAILED
# --------------------------------------------------------------------
class FailingCapabilityTests(unittest.TestCase):
    def test_failing_capability_produces_failed(self):
        with tempfile.TemporaryDirectory() as sandbox:
            capability_path = os.path.join(sandbox, "demo_capability.py")
            _write(capability_path, PASSING_MODULE)
            _write(os.path.join(sandbox, "test_demo_capability.py"), FAILING_TEST)

            apply_result = _apply_result(file_path=capability_path)
            result = run_capability_tests(
                apply_result, project_dir=sandbox, test_target="test_demo_capability",
            )

            self.assertEqual(result["status"], STATUS_FAILED)
            self.assertEqual(result["tests_run"], 1)
            self.assertEqual(result["tests_failed"], 1)
            self.assertEqual(result["tests_passed"], 0)
            self.assertTrue(any(err for err in result["errors"]))


# --------------------------------------------------------------------
# Timeout handled correctly
# --------------------------------------------------------------------
class TimeoutCapabilityTests(unittest.TestCase):
    def test_slow_test_times_out(self):
        with tempfile.TemporaryDirectory() as sandbox:
            capability_path = os.path.join(sandbox, "demo_capability.py")
            _write(capability_path, PASSING_MODULE)
            _write(os.path.join(sandbox, "test_slow.py"), SLOW_TEST)

            apply_result = _apply_result(file_path=capability_path)
            result = run_capability_tests(
                apply_result, project_dir=sandbox, test_target="test_slow",
                timeout_seconds=1,
            )

            self.assertEqual(result["status"], STATUS_TIMEOUT)
            self.assertEqual(result["timeout_seconds"], 1)
            self.assertIsNone(result["tests_run"])


# --------------------------------------------------------------------
# Invalid application result rejected
# --------------------------------------------------------------------
class InvalidApplyResultTests(unittest.TestCase):
    def test_invalid_apply_status_is_rejected(self):
        apply_result = _apply_result(status=APPLY_STATUS_INVALID, file_path=None)
        result = run_capability_tests(apply_result, project_dir="/tmp", test_target="test_x")
        self.assertEqual(result["status"], STATUS_INVALID)
        self.assertIsNone(result["tests_run"])

    def test_not_a_dict_is_invalid(self):
        result = run_capability_tests("not a result", project_dir="/tmp", test_target="test_x")
        self.assertEqual(result["status"], STATUS_INVALID)

    def test_missing_test_target_is_invalid(self):
        with tempfile.TemporaryDirectory() as sandbox:
            capability_path = os.path.join(sandbox, "demo_capability.py")
            _write(capability_path, PASSING_MODULE)
            apply_result = _apply_result(file_path=capability_path)
            result = run_capability_tests(apply_result, project_dir=sandbox, test_target="")
            self.assertEqual(result["status"], STATUS_INVALID)

    def test_missing_file_on_disk_is_invalid(self):
        with tempfile.TemporaryDirectory() as sandbox:
            missing_path = os.path.join(sandbox, "does_not_exist.py")
            apply_result = _apply_result(file_path=missing_path)
            result = run_capability_tests(
                apply_result, project_dir=sandbox, test_target="test_demo_capability",
            )
            self.assertEqual(result["status"], STATUS_INVALID)

    def test_unvalidated_source_is_invalid(self):
        with tempfile.TemporaryDirectory() as sandbox:
            capability_path = os.path.join(sandbox, "demo_capability.py")
            _write(capability_path, PASSING_MODULE)
            _write(os.path.join(sandbox, "test_demo_capability.py"), PASSING_TEST)
            apply_result = _apply_result(
                file_path=capability_path,
                validation_result={"status": VALIDATION_INVALID, "error": "bad", "target_file": None, "generated_code": None, "analysis": None},
            )
            result = run_capability_tests(
                apply_result, project_dir=sandbox, test_target="test_demo_capability",
            )
            self.assertEqual(result["status"], STATUS_INVALID)


# --------------------------------------------------------------------
# Blocked path never executed
# --------------------------------------------------------------------
class BlockedPathTests(unittest.TestCase):
    def test_upstream_blocked_apply_result_never_executes(self):
        apply_result = _apply_result(status=APPLY_STATUS_BLOCKED, file_path=None)
        result = run_capability_tests(apply_result, project_dir="/tmp", test_target="test_x")
        self.assertEqual(result["status"], STATUS_BLOCKED)
        self.assertIsNone(result["tests_run"])

    def test_file_outside_allowed_dirs_is_blocked(self):
        with tempfile.TemporaryDirectory() as sandbox, \
                tempfile.TemporaryDirectory() as other_dir:
            capability_path = os.path.join(other_dir, "demo_capability.py")
            _write(capability_path, PASSING_MODULE)
            _write(os.path.join(sandbox, "test_demo_capability.py"), PASSING_TEST)

            apply_result = _apply_result(file_path=capability_path)
            result = run_capability_tests(
                apply_result, project_dir=sandbox, test_target="test_demo_capability",
                allowed_dirs=[sandbox],
            )
            self.assertEqual(result["status"], STATUS_BLOCKED)
            self.assertIsNone(result["tests_run"])


# --------------------------------------------------------------------
# Existing project behavior remains unchanged
# --------------------------------------------------------------------
class ExistingBehaviorUnchangedTests(unittest.TestCase):
    def test_apply_chain_still_behaves_as_before(self):
        apply_request = _real_applied_result()
        self.assertIn(apply_request["status"], ("READY", "BLOCKED", "INVALID"))

    def test_statuses_are_fixed(self):
        self.assertEqual(
            set(ALL_STATUSES),
            {STATUS_PASSED, STATUS_FAILED, STATUS_TIMEOUT, STATUS_BLOCKED, STATUS_INVALID},
        )

    def test_does_not_mutate_apply_result(self):
        with tempfile.TemporaryDirectory() as sandbox:
            capability_path = os.path.join(sandbox, "demo_capability.py")
            _write(capability_path, PASSING_MODULE)
            _write(os.path.join(sandbox, "test_demo_capability.py"), PASSING_TEST)

            apply_result = _apply_result(file_path=capability_path)
            before = dict(apply_result)
            run_capability_tests(apply_result, project_dir=sandbox, test_target="test_demo_capability")
            self.assertEqual(apply_result, before)

    def test_real_project_tree_is_never_touched(self):
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        marker_file = os.path.join(project_root, "self_upgrade", "capability_test_execution.py")
        before_mtime = os.path.getmtime(marker_file)

        with tempfile.TemporaryDirectory() as sandbox:
            capability_path = os.path.join(sandbox, "demo_capability.py")
            _write(capability_path, PASSING_MODULE)
            _write(os.path.join(sandbox, "test_demo_capability.py"), PASSING_TEST)
            apply_result = _apply_result(file_path=capability_path)
            run_capability_tests(apply_result, project_dir=sandbox, test_target="test_demo_capability")

        after_mtime = os.path.getmtime(marker_file)
        self.assertEqual(before_mtime, after_mtime)


if __name__ == "__main__":
    unittest.main()
