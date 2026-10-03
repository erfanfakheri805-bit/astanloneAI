"""
Tests for the built-in `python_test_runner` capability
(execution/python_test_runner_capability.py) - a real,
standard-library-only `Capability` that runs a project's Python tests
(via `python -m unittest`, invoked as a fixed argument list - never a
shell command) inside an allowed project directory only, and reports a
structured pass/fail result.

Covers: a valid test target being executable; a successful test run
producing a successful structured result; a failing test run producing
a failed structured result; invalid/unsafe project paths being
rejected; a hanging test being handled safely by the configured
timeout; and the capability being registered and executable through
the existing `ExecutableCapabilityRegistry` / `ExecutionEngine`
capability system.

Every test uses its own isolated temporary directory as the allowed
project directory (via `allowed_dirs=`) - never the application's real
data/skills/temp directories - so this suite never touches, creates,
or depends on anything outside its own `tempfile.TemporaryDirectory`.

Run directly:
    python -m unittest tests.test_python_test_runner_capability -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from execution.capability import Capability
from execution.capability_handlers import CapabilityHandlerRegistry
from execution.executable_registry import ExecutableCapabilityRegistry
from execution.execution_engine import ExecutionEngine
from execution.execution_result import STATUS_COMPLETED, STATUS_FAILED
from execution.python_test_runner_capability import (
    CAPABILITY_NAME,
    create_python_test_runner_capability,
    register_python_test_runner_capability,
)
from planning.goal_manager import GoalManager
from planning.plan_manager import PlanManager


PASSING_TEST_SOURCE = (
    "import unittest\n\n"
    "class TestPassing(unittest.TestCase):\n"
    "    def test_ok(self):\n"
    "        self.assertEqual(1 + 1, 2)\n"
)

FAILING_TEST_SOURCE = (
    "import unittest\n\n"
    "class TestFailing(unittest.TestCase):\n"
    "    def test_not_ok(self):\n"
    "        self.assertEqual(1 + 1, 3)\n"
)

HANGING_TEST_SOURCE = (
    "import time\n"
    "import unittest\n\n"
    "class TestHanging(unittest.TestCase):\n"
    "    def test_hangs(self):\n"
    "        time.sleep(60)\n"
)


class PythonTestRunnerCapabilityTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.allowed_dir = self._tmp.name
        self.addCleanup(self._tmp.cleanup)

    def _write(self, *relative_parts, content=""):
        path = os.path.join(self.allowed_dir, *relative_parts)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        return path

    def _capability(self, **kwargs):
        return create_python_test_runner_capability(
            allowed_dirs=[self.allowed_dir], **kwargs
        )

    def _snapshot(self):
        """A plain (path -> mtime/size) fingerprint of everything under
        the allowed dir, used to assert the capability never modifies
        the project it runs tests in."""
        fingerprint = {}
        for current_dir, dir_names, file_names in os.walk(self.allowed_dir):
            for name in dir_names + file_names:
                full_path = os.path.join(current_dir, name)
                stat = os.stat(full_path)
                fingerprint[full_path] = (stat.st_mtime_ns, stat.st_size)
        return fingerprint


# ----------------------------------------------------------------------
# 1. A valid test target can be executed
# ----------------------------------------------------------------------
class TestValidTestTargetCanBeExecuted(PythonTestRunnerCapabilityTestBase):
    def test_file_target_runs(self):
        self._write("test_thing.py", content=PASSING_TEST_SOURCE)
        capability = self._capability()

        result = capability.execute({"path": self.allowed_dir, "target": "test_thing.py"})

        self.assertTrue(result.success)
        self.assertEqual(result.output["return_code"], 0)

    def test_dotted_target_runs(self):
        self._write("test_thing.py", content=PASSING_TEST_SOURCE)
        capability = self._capability()

        result = capability.execute(
            {"path": self.allowed_dir, "target": "test_thing.TestPassing.test_ok"}
        )

        self.assertTrue(result.success)
        self.assertEqual(result.output["return_code"], 0)

    def test_discovery_with_no_target_runs(self):
        self._write("test_thing.py", content=PASSING_TEST_SOURCE)
        capability = self._capability()

        result = capability.execute({"path": self.allowed_dir})

        self.assertTrue(result.success)
        self.assertIsNone(result.output["target"])


# ----------------------------------------------------------------------
# 2. Successful tests return a successful structured result
# ----------------------------------------------------------------------
class TestSuccessfulTestsReturnSuccessfulResult(PythonTestRunnerCapabilityTestBase):
    def test_success_flag_is_true(self):
        self._write("test_thing.py", content=PASSING_TEST_SOURCE)
        capability = self._capability()

        result = capability.execute({"path": self.allowed_dir, "target": "test_thing.py"})

        self.assertTrue(result.output["success"])
        self.assertFalse(result.output["timed_out"])

    def test_test_counts_are_reported(self):
        self._write("test_thing.py", content=PASSING_TEST_SOURCE)
        capability = self._capability()

        result = capability.execute({"path": self.allowed_dir, "target": "test_thing.py"})

        self.assertEqual(result.output["tests_run"], 1)
        self.assertEqual(result.output["failures"], 0)
        self.assertEqual(result.output["errors"], 0)

    def test_does_not_modify_project_files(self):
        self._write("test_thing.py", content=PASSING_TEST_SOURCE)
        fingerprint_before = self._snapshot()
        capability = self._capability()

        capability.execute({"path": self.allowed_dir, "target": "test_thing.py"})

        self.assertEqual(self._snapshot(), fingerprint_before)


# ----------------------------------------------------------------------
# 3. Failing tests return a failed structured result
# ----------------------------------------------------------------------
class TestFailingTestsReturnFailedResult(PythonTestRunnerCapabilityTestBase):
    def test_success_flag_is_false(self):
        self._write("test_thing.py", content=FAILING_TEST_SOURCE)
        capability = self._capability()

        result = capability.execute({"path": self.allowed_dir, "target": "test_thing.py"})

        # The capability itself ran cleanly (no exception, no invalid
        # input) - only the tests it ran failed, so the overall
        # Capability.execute call is still a success...
        self.assertTrue(result.success)
        # ...but the structured test-run output reports failure.
        self.assertFalse(result.output["success"])
        self.assertNotEqual(result.output["return_code"], 0)

    def test_failure_count_is_reported(self):
        self._write("test_thing.py", content=FAILING_TEST_SOURCE)
        capability = self._capability()

        result = capability.execute({"path": self.allowed_dir, "target": "test_thing.py"})

        self.assertEqual(result.output["tests_run"], 1)
        self.assertEqual(result.output["failures"], 1)

    def test_stderr_output_is_captured(self):
        self._write("test_thing.py", content=FAILING_TEST_SOURCE)
        capability = self._capability()

        result = capability.execute({"path": self.allowed_dir, "target": "test_thing.py"})

        self.assertIn("FAILED", result.output["stderr"])


# ----------------------------------------------------------------------
# 4. Invalid or unsafe project paths are rejected
# ----------------------------------------------------------------------
class TestInvalidOrUnsafePathsAreRejected(PythonTestRunnerCapabilityTestBase):
    def test_path_outside_allowed_dir_is_rejected(self):
        with tempfile.TemporaryDirectory() as other_dir:
            capability = self._capability()

            result = capability.execute({"path": other_dir})

            self.assertFalse(result.success)
            self.assertIn("outside", result.error.lower())

    def test_traversal_out_of_allowed_dir_is_rejected(self):
        with tempfile.TemporaryDirectory() as other_dir:
            traversal_path = os.path.join(
                self.allowed_dir, "..", os.path.basename(other_dir)
            )
            capability = self._capability()

            result = capability.execute({"path": traversal_path})

            self.assertFalse(result.success)

    def test_missing_directory_is_rejected(self):
        missing_path = os.path.join(self.allowed_dir, "does_not_exist")
        capability = self._capability()

        result = capability.execute({"path": missing_path})

        self.assertFalse(result.success)

    def test_file_path_instead_of_directory_is_rejected(self):
        path = self._write("readme.txt", content="hello")
        capability = self._capability()

        result = capability.execute({"path": path})

        self.assertFalse(result.success)

    def test_target_escaping_the_project_directory_is_rejected(self):
        self._write("test_thing.py", content=PASSING_TEST_SOURCE)
        with tempfile.TemporaryDirectory() as other_dir:
            with open(os.path.join(other_dir, "test_evil.py"), "w", encoding="utf-8") as fh:
                fh.write(PASSING_TEST_SOURCE)
            escaping_target = os.path.join(
                "..", os.path.basename(other_dir), "test_evil.py"
            )
            capability = self._capability()

            result = capability.execute({"path": self.allowed_dir, "target": escaping_target})

            self.assertFalse(result.success)
            self.assertIn("outside", result.error.lower())

    def test_target_that_looks_like_a_flag_is_rejected(self):
        self._write("test_thing.py", content=PASSING_TEST_SOURCE)
        capability = self._capability()

        result = capability.execute({"path": self.allowed_dir, "target": "--help"})

        self.assertFalse(result.success)

    def test_missing_target_file_is_rejected(self):
        capability = self._capability()

        result = capability.execute(
            {"path": self.allowed_dir, "target": "does_not_exist.py"}
        )

        self.assertFalse(result.success)


# ----------------------------------------------------------------------
# 5. Timeout is handled safely
# ----------------------------------------------------------------------
class TestTimeoutIsHandledSafely(PythonTestRunnerCapabilityTestBase):
    def test_hanging_test_is_reported_as_timed_out_not_raised(self):
        self._write("test_thing.py", content=HANGING_TEST_SOURCE)
        capability = self._capability(timeout_seconds=1)

        result = capability.execute({"path": self.allowed_dir, "target": "test_thing.py"})

        # A timeout is a normal, structured outcome - never an
        # uncaught exception propagating out of execute().
        self.assertTrue(result.success)
        self.assertTrue(result.output["timed_out"])
        self.assertFalse(result.output["success"])
        self.assertIsNone(result.output["return_code"])

    def test_timeout_does_not_leave_project_files_modified(self):
        self._write("test_thing.py", content=HANGING_TEST_SOURCE)
        fingerprint_before = self._snapshot()
        capability = self._capability(timeout_seconds=1)

        capability.execute({"path": self.allowed_dir, "target": "test_thing.py"})

        self.assertEqual(self._snapshot(), fingerprint_before)


# ----------------------------------------------------------------------
# 6. Registered and executable through the existing capability system
# ----------------------------------------------------------------------
class TestRegisteredAndExecutableThroughCapabilitySystem(PythonTestRunnerCapabilityTestBase):
    def test_capability_is_a_real_capability_instance(self):
        capability = self._capability()
        self.assertIsInstance(capability, Capability)
        self.assertEqual(capability.name, CAPABILITY_NAME)

    def test_registers_into_executable_capability_registry(self):
        registry = ExecutableCapabilityRegistry()
        register_python_test_runner_capability(registry, allowed_dirs=[self.allowed_dir])

        self.assertTrue(registry.has(CAPABILITY_NAME))
        self.assertTrue(registry.is_available(CAPABILITY_NAME))

    def test_registers_into_capability_handler_registry(self):
        registry = CapabilityHandlerRegistry()
        register_python_test_runner_capability(registry, allowed_dirs=[self.allowed_dir])

        self.assertTrue(registry.is_capability(CAPABILITY_NAME))

    def test_executable_via_executable_capability_registry_directly(self):
        self._write("test_thing.py", content=PASSING_TEST_SOURCE)
        registry = ExecutableCapabilityRegistry()
        register_python_test_runner_capability(registry, allowed_dirs=[self.allowed_dir])

        capability = registry.get(CAPABILITY_NAME)
        result = capability.execute({"path": self.allowed_dir, "target": "test_thing.py"})

        self.assertTrue(result.success)
        self.assertTrue(result.output["success"])

    def test_executable_through_execution_engine(self):
        self._write("test_thing.py", content=PASSING_TEST_SOURCE)
        goals = GoalManager()
        plans = PlanManager(goals)
        engine = ExecutionEngine(plans)
        register_python_test_runner_capability(
            engine.executable_capabilities, allowed_dirs=[self.allowed_dir]
        )

        result = engine.execute_registered_capability(
            CAPABILITY_NAME, {"path": self.allowed_dir, "target": "test_thing.py"}
        )

        self.assertEqual(result.status, STATUS_COMPLETED)
        self.assertTrue(result.output["success"])

    def test_disabled_registration_is_not_executable_through_engine(self):
        goals = GoalManager()
        plans = PlanManager(goals)
        engine = ExecutionEngine(plans)
        register_python_test_runner_capability(
            engine.executable_capabilities,
            allowed_dirs=[self.allowed_dir],
            enabled=False,
        )

        result = engine.execute_registered_capability(
            CAPABILITY_NAME, {"path": self.allowed_dir}
        )

        self.assertEqual(result.status, STATUS_FAILED)


if __name__ == "__main__":
    unittest.main()
